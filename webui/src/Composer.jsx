// Bottom composer: task input + voice dictation (AudioContext → PCM16 WAV
// @16kHz → POST /api/stt) + send button. Ctrl+Enter sends too.
import { useRef, useState } from "react";
import BottomNavigation from "@mui/material/BottomNavigation";
import BottomNavigationAction from "@mui/material/BottomNavigationAction";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Grid from "@mui/material/Grid";
import IconButton from "@mui/material/IconButton";
import Paper from "@mui/material/Paper";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import MicIcon from "@mui/icons-material/Mic";
import MenuIcon from "@mui/icons-material/Menu";
import HourglassEmptyIcon from "@mui/icons-material/HourglassEmpty";
import SendIcon from "@mui/icons-material/Send";
import RefreshIcon from "@mui/icons-material/Refresh";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import CodeIcon from "@mui/icons-material/Code";
import QuestionAnswerIcon from "@mui/icons-material/QuestionAnswer";
import useMediaQuery from "@mui/material/useMediaQuery";
import { api, post } from "./api.js";

const STT_RATE = 16000;
const fmtDur = s => String(Math.floor(s / 60)).padStart(2, "0") + ":" +
                    String(Math.floor(s % 60)).padStart(2, "0");

function resample(chunks, srcRate, dstRate) {
  const srcLen = chunks.reduce((a, c) => a + c.length, 0);
  const src = new Float32Array(srcLen);
  let off = 0;
  for (const c of chunks) { src.set(c, off); off += c.length; }
  if (srcRate === dstRate || !srcLen) return [src];
  const dstLen = Math.round(srcLen * dstRate / srcRate);
  const dst = new Float32Array(dstLen);
  const ratio = srcRate / dstRate;
  for (let i = 0; i < dstLen; i++) {
    const p = i * ratio, i0 = Math.floor(p),
          i1 = Math.min(i0 + 1, srcLen - 1), f = p - i0;
    dst[i] = src[i0] + (src[i1] - src[i0]) * f;
  }
  return [dst];
}

function encodeWav(chunks, rate) {
  const len = chunks.reduce((a, c) => a + c.length, 0);
  const buf = new ArrayBuffer(44 + len * 2), v = new DataView(buf);
  const ws = (o, s) => { for (let i = 0; i < s.length; i++)
    v.setUint8(o + i, s.charCodeAt(i)); };
  ws(0, "RIFF"); v.setUint32(4, 36 + len * 2, true); ws(8, "WAVEfmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  ws(36, "data"); v.setUint32(40, len * 2, true);
  let o = 44;
  for (const ch of chunks)
    for (let i = 0; i < ch.length; i++, o += 2) {
      const s = Math.max(-1, Math.min(1, ch[i]));
      v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }
  return buf;
}

export default function Composer({ project, sttStatus, toast, onSent,
                                   conn, onOpenDrawer, accent, onOpenModels, mode, onMode }) {
  // <md = phone layout: single bottom-nav bar
  const mobile = useMediaQuery(t => t.breakpoints.down("md"));
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [recInfo, setRecInfo] = useState("");  // timer/status line near the mic
  const recRef = useRef(null);
  const [recording, setRecording] = useState(false);
  const [recognizing, setRecognizing] = useState(false);
  const [lastAudio, setLastAudio] = useState(null);  // failed WAV → retry

  const send = async () => {
    const t = text.trim();
    if (!t) return;
    setBusy(true);
    try {
      const d = await post("/api/tasks", {
        project: project === "workspace" ? null : project, text: t });
      if (d.ok) { setText(""); onSent?.(); }
      else toast("Ошибка: " + (d.error || "?"));
    } catch (e) { toast("Сеть: " + e); }
    setBusy(false);
  };

  const stopRec = async r => {
    recRef.current = null;
    setRecording(false);
    clearTimeout(r.timer); clearInterval(r.clock);
    r.proc.disconnect(); r.src.disconnect(); r.gain.disconnect();
    r.stream.getTracks().forEach(t => t.stop());
    const wav = encodeWav(resample(r.chunks, r.ctx.sampleRate, STT_RATE),
                          STT_RATE);
    r.ctx.close();
    sendAudio(wav);
  };

  // POST the WAV to STT. On any failure keep the blob in lastAudio —
  // providers (yandex etc.) often recover within seconds, the «ещё раз»
  // button resends it so the recording isn't lost.
  const sendAudio = async wav => {
    setRecognizing(true);
    setRecInfo("распознаю…");
    try {
      const d = await (await api("/api/stt", { method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: wav })).json();
      if (d.ok && d.text.trim()) {
        setText(prev => (prev ? prev.replace(/\s+$/, "") + " " : "") +
                        d.text.trim());
        setLastAudio(null);
      } else {
        toast(d.ok ? "Ничего не распознано"
                   : "STT: " + (d.error || "?"));
        setLastAudio(wav);
      }
    } catch (e) {
      toast("STT сеть: " + e);
      setLastAudio(wav);
    }
    setRecognizing(false);
    setRecInfo("");
  };

  const startRec = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new (window.AudioContext || window.webkitAudioContext)(
        { sampleRate: STT_RATE });   // Safari may ignore — resampled anyway
      const src = ctx.createMediaStreamSource(stream);
      const proc = ctx.createScriptProcessor(4096, 1, 1);
      const gain = ctx.createGain();       // silence — prevents echo
      gain.gain.value = 0;
      const chunks = [];
      proc.onaudioprocess = e =>
        chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      src.connect(proc); proc.connect(gain); gain.connect(ctx.destination);
      const t0 = Date.now();
      const r = { ctx, proc, src, gain, stream, chunks,
        clock: setInterval(
          () => setRecInfo(fmtDur((Date.now() - t0) / 1000)), 250),
        timer: setTimeout(() => { if (recRef.current) micClick(); }, 300000) };
      recRef.current = r;
      setRecording(true);
      setRecInfo("00:00");
    } catch (e) { toast("Микрофон: " + e); }
  };

  const micClick = () => {
    const r = recRef.current;
    if (r) stopRec(r); else startRec();
  };

  const shownStat = recognizing && sttStatus ? sttStatus : recInfo;

  const modeBtn = (
    <IconButton size="small" disabled={!project} onClick={() =>
                    onMode && onMode(mode === "ask" ? "code" : "ask")}
                title={mode === "ask" ? "Режим: вопрос — нажми для кода"
                                      : "Режим: код — нажми для вопроса"}
                sx={{ flexShrink: 0, mb: "2px" }}>
      {mode === "ask" ? <QuestionAnswerIcon fontSize="small" />
                      : <CodeIcon fontSize="small" />}
    </IconButton>
  );

  if (mobile) return (
    <Paper elevation={6} sx={{
      position: "fixed", left: 0, right: 0, bottom: 0, zIndex: 10,
      borderRadius: 0 }}>
      <Box sx={{ px: 1, pt: 0.8, pb: "5px",
                 display: "flex", alignItems: "flex-end", gap: 0.5 }}>
        {modeBtn}
        <TextField
          multiline minRows={1} maxRows={50} fullWidth size="small"
          sx={{ "& .MuiInputBase-root": { maxHeight: "80vh",
                                          overflowY: "auto" } }}
          placeholder={mode === "ask" ? `Вопрос по «${project || "…"}»`
                            : `Задача для «${project || "…"}»`}
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault(); send();
            }
          }}
          sx={{ "& .MuiOutlinedInput-root": { borderRadius: 2 } }} />
        {shownStat && (
          <Typography variant="caption" color="text.secondary"
                      sx={{ display: "block", pt: 0.2, fontSize: 11 }}>
            {shownStat}
          </Typography>
        )}
      </Box>
      <BottomNavigation showLabels sx={{
        height: 52, bgcolor: accent || "primary.main",
        "& .MuiBottomNavigationAction-root": {
          color: "rgba(255,255,255,.72)" },
        "& .MuiBottomNavigationAction-root.Mui-selected": {
          color: "#fff" },
      }}>
        <BottomNavigationAction label="Меню" icon={<MenuIcon />}
                                onClick={onOpenDrawer}
                                sx={{ minWidth: 0 }} />
        <BottomNavigationAction
          label={recording ? "Стоп" : "Запись"}
          icon={recognizing ? <HourglassEmptyIcon /> : <MicIcon />}
          onClick={micClick}
          sx={{ minWidth: 0,
                color: recording ? "error.light" : "#fff",
                ...(recording && {
                  animation: "pulse 1s infinite",
                  "@keyframes pulse": { "50%": { opacity: 0.35 } } }) }} />
        {lastAudio && !recognizing && (
          <BottomNavigationAction label="Ещё раз"
            icon={<RefreshIcon />}
            onClick={() => sendAudio(lastAudio)}
            sx={{ minWidth: 0, color: "warning.light" }} />
        )}
        <BottomNavigationAction label="В работу" icon={<SendIcon />}
          onClick={send} disabled={busy || !text.trim()}
          sx={{ minWidth: 0,
                color: text.trim() ? "#fff" : "rgba(255,255,255,.4)" }} />
        <BottomNavigationAction label="Модели" icon={<SmartToyIcon />}
          onClick={onOpenModels}
          sx={{ minWidth: 0, color: "#fff" }} />
      </BottomNavigation>
    </Paper>
  );

  return (
    <Paper elevation={4} sx={{
      position: "fixed", left: 0, right: 0, bottom: 0, zIndex: 10,
      borderRadius: 0 }}>
      <Grid container spacing={1} sx={{
        maxWidth: 1280, mx: "auto", p: 1.5, alignItems: "flex-end" }}>
        <Grid size={{ xs: 12, sm: "grow" }}>
          <TextField
            multiline minRows={1} maxRows={50} fullWidth size="small"
            sx={{ "& .MuiInputBase-root": { maxHeight: "80vh",
                                            overflowY: "auto" } }}
            placeholder={(mode === "ask"
             ? `Вопрос по «${project || "…"}»`
             : `Задача для Devin по проекту «${project || "…"}»`) +
                         " — Ctrl+Enter чтобы отправить"}
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault(); send();
              }
            }}
            sx={{ "& .MuiOutlinedInput-root": { borderRadius: 2 } }} />
        </Grid>
        <Grid size={{ xs: 12, sm: "auto" }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 0.8,
                     justifyContent: "flex-end", flexWrap: "nowrap" }}>
            {modeBtn}
            <IconButton onClick={micClick} size="small"
                        color={recording ? "error" : "default"}
                        title="надиктовать голосом"
                        sx={recording
                          ? { animation: "pulse 1s infinite",
                              "@keyframes pulse":
                                { "50%": { opacity: 0.35 } } }
                          : {}}>
              {recognizing ? <HourglassEmptyIcon /> : <MicIcon />}
            </IconButton>
            {lastAudio && !recognizing && (
              <Button size="small" variant="outlined" color="warning"
                      startIcon={<RefreshIcon sx={{ fontSize: 15 }} />}
                      onClick={() => sendAudio(lastAudio)}
                      title="отправить запись на распознавание ещё раз"
                      sx={{ textTransform: "none", whiteSpace: "nowrap",
                            fontSize: 12, px: 1, minWidth: 0 }}>
                ещё раз
              </Button>
            )}
            <Typography variant="caption" color="text.secondary"
                        sx={{ minWidth: 38, whiteSpace: "nowrap",
                              textAlign: "center" }}>
              {shownStat}
            </Typography>
            <Button variant="contained" size="small" onClick={send}
                    disabled={busy} endIcon={<SendIcon sx={{fontSize: 15}} />}
                    sx={{ whiteSpace: "nowrap", px: 1.5, minWidth: 0 }}>
              В работу
            </Button>
          </Box>
        </Grid>
      </Grid>
    </Paper>
  );
}
