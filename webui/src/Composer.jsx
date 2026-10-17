// Bottom composer: task input + voice dictation (AudioContext → PCM16 WAV
// @16kHz → POST /api/stt) + send button. Ctrl+Enter sends too.
import { useRef, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Paper from "@mui/material/Paper";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import MicIcon from "@mui/icons-material/Mic";
import HourglassEmptyIcon from "@mui/icons-material/HourglassEmpty";
import SendIcon from "@mui/icons-material/Send";
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

export default function Composer({ project, sttStatus, toast, onSent }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [recInfo, setRecInfo] = useState("");  // timer/status line near the mic
  const recRef = useRef(null);
  const [recording, setRecording] = useState(false);
  const [recognizing, setRecognizing] = useState(false);

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
    setRecognizing(true);
    setRecInfo("распознаю…");
    try {
      const d = await (await api("/api/stt", { method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: wav })).json();
      if (d.ok && d.text.trim())
        setText(prev => (prev ? prev.replace(/\s+$/, "") + " " : "") +
                        d.text.trim());
      else if (!d.ok) toast("STT: " + (d.error || "?"));
      else toast("Ничего не распознано");
    } catch (e) { toast("STT сеть: " + e); }
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

  return (
    <Paper elevation={4} sx={{
      position: "fixed", left: 0, right: 0, bottom: 0, zIndex: 10,
      borderRadius: 0 }}>
      <Box sx={{
        maxWidth: 1280, mx: "auto", display: "flex", gap: 1.5, p: 1.5,
        alignItems: "flex-end", flexWrap: { xs: "wrap", sm: "nowrap" } }}>
        <TextField
          multiline minRows={1} maxRows={6} fullWidth size="small"
          placeholder={`Задача для Devin по проекту «${project || "…"}» — ` +
                       "Ctrl+Enter чтобы отправить"}
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault(); send();
            }
          }}
          sx={{ flex: { xs: "1 1 100%", sm: 1 },
                "& .MuiOutlinedInput-root": { borderRadius: 2 } }} />
        <IconButton onClick={micClick}
                    color={recording ? "error" : "default"}
                    title="надиктовать голосом"
                    sx={recording
                      ? { animation: "pulse 1s infinite",
                          "@keyframes pulse": { "50%": { opacity: 0.35 } } }
                      : {}}>
          {recognizing ? <HourglassEmptyIcon /> : <MicIcon />}
        </IconButton>
        <Typography variant="caption" color="text.secondary"
                    sx={{ minWidth: 44, pb: 1.2, whiteSpace: "nowrap" }}>
          {shownStat}
        </Typography>
        <Button variant="contained" onClick={send} disabled={busy}
                endIcon={<SendIcon />} sx={{ flex: { xs: 1, sm: "0 0 auto" } }}>
          В работу
        </Button>
      </Box>
    </Paper>
  );
}
