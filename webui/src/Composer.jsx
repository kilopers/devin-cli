// Bottom composer: task input + voice dictation (AudioContext → PCM16 WAV
// @16kHz → POST /api/stt) + send button. Ctrl+Enter sends too.
import { useEffect, useRef, useState } from "react";
import BottomNavigation from "@mui/material/BottomNavigation";
import BottomNavigationAction from "@mui/material/BottomNavigationAction";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Grid from "@mui/material/Grid";
import IconButton from "@mui/material/IconButton";
import Paper from "@mui/material/Paper";
import TextField from "@mui/material/TextField";
import Chip from "@mui/material/Chip";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Typography from "@mui/material/Typography";
import MicIcon from "@mui/icons-material/Mic";
import MenuIcon from "@mui/icons-material/Menu";
import HourglassEmptyIcon from "@mui/icons-material/HourglassEmpty";
import SendIcon from "@mui/icons-material/Send";
import RefreshIcon from "@mui/icons-material/Refresh";
import PsychologyIcon from "@mui/icons-material/Psychology";
import AttachFileIcon from "@mui/icons-material/AttachFile";
import FlashOnIcon from "@mui/icons-material/FlashOn";
import FlashOffIcon from "@mui/icons-material/FlashOff";
import useMediaQuery from "@mui/material/useMediaQuery";
import { api, apiJson as get, post } from "./api.js";
import { STT_RATE, resample, encodeWav } from "./audio.js";
import Discuss from "./Discuss.jsx";

const fmtDur = s => String(Math.floor(s / 60)).padStart(2, "0") + ":" +
                    String(Math.floor(s % 60)).padStart(2, "0");

export default function Composer({ project, sttStatus, toast, onSent,
                                   conn, onOpenDrawer, accent, mode, onMode,
                                   fast, onFast, collect, onCollect }) {
  // <md = phone layout: single bottom-nav bar
  const mobile = useMediaQuery(t => t.breakpoints.down("md"));
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [recInfo, setRecInfo] = useState("");  // timer/status line near the mic
  const recRef = useRef(null);
  const [recording, setRecording] = useState(false);
  const [recognizing, setRecognizing] = useState(false);
  const [lastAudio, setLastAudio] = useState(null);  // failed WAV → retry
  const [discussOpen, setDiscussOpen] = useState(false);
  const textRef = useRef("");
  textRef.current = text;

  // чипы параметров следующей задачи: проектные дефолты + разовые
  // оверрайды (действуют только на ближайшую отправку)
  const [eff, setEff] = useState({ model: "", mode: "code", ac: "0" });
  const [ov, setOv] = useState({});       // {mode?, ac?, model?}
  const [models, setModels] = useState([]);
  const [att, setAtt] = useState(null);     // {id, name} прикреплённый файл
  const fileRef = useRef(null);
  const [mAnchor, setMAnchor] = useState(null);
  useEffect(() => {
    if (!project || project === "workspace") return;
    get("/api/project/settings?project=" + encodeURIComponent(project))
      .then(j => setEff({ model: j.eff_model || "",
                          mode: j.eff_mode || "code",
                          ac: j.auto_commit || "0" }))
      .catch(() => {});
    get("/api/models").then(j => setModels(j.models || [])).catch(()=>{});
    setOv({});
  }, [project]);

  const curMode = ov.mode ?? eff.mode;
  const curAc = ov.ac ?? eff.ac;
  const curModel = ov.model ?? eff.model;

  const pickFile = async e => {
    const fl = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!fl) return;
    if (fl.size > 20 * 1024 * 1024) { toast("Файл > 20 МБ"); return; }
    try {
      const d = await (await api("/api/attach?name=" +
        encodeURIComponent(fl.name), { method: "POST", body: fl })).json();
      if (d.ok) setAtt({ id: d.id, name: d.name });
      else toast("Файл: " + (d.error || "?"));
    } catch (err) { toast("Сеть: " + err); }
  };
  const fileInput = (
    <input ref={fileRef} type="file" hidden onChange={pickFile} />);
  // единый стиль мета-чипов (как на карточках задач)
  const chipSx = { height: 24, fontSize: 11.5, fontWeight: 500,
                   borderRadius: "7px",
                   "& .MuiChip-label": { px: "9px" } };
  const attChip = att && (
    <Chip size="small" icon={<AttachFileIcon />} label={att.name}
          sx={chipSx} color="primary" variant="outlined"
          onDelete={() => setAtt(null)} title="прикреплённый файл — убрать" />);
  const chips = (
    <Box sx={{ display: "flex", gap: 0.7, flexWrap: "nowrap",
               justifyContent: "flex-start", overflowX: "auto", px: 0.5,
               pt: 1, pb: 0.9,
               "& .MuiChip-root": { flexShrink: 0 },
               "&::-webkit-scrollbar": { display: "none" } }}>
      {attChip}
      <Chip size="small" clickable sx={chipSx}
        label={curMode === "ask" ? "💬 Спросить" : "🛠 Код"}
        color={ov.mode ? "primary" : "default"}
        variant={ov.mode ? "filled" : "outlined"}
        onClick={() => setOv({ ...ov,
          mode: curMode === "ask" ? "code" : "ask" })}
        title={"режим следующей задачи" + (ov.mode ? " (разово)" : "")} />
      <Chip size="small" clickable sx={chipSx}
        label={curAc === "1" ? "Автокоммит" : "Ручной коммит"}
        color={ov.ac ? "primary" : "default"}
        variant={ov.ac ? "filled" : "outlined"}
        onClick={() => setOv({ ...ov, ac: curAc === "1" ? "0" : "1" })}
        title={"коммит после задачи" + (ov.ac ? " (разово)" : "")} />
      <Chip size="small" clickable sx={chipSx}
        label={"Модель: " + (curModel || "—")}
        color={ov.model ? "primary" : "default"}
        variant={ov.model ? "filled" : "outlined"}
        onClick={e => setMAnchor(e.currentTarget)}
        title={"модель следующей задачи" + (ov.model ? " (разово)" : "")} />
      <Menu anchorEl={mAnchor} open={!!mAnchor}
            onClose={() => setMAnchor(null)}>
        {models.map(m => (
          <MenuItem key={m.id} dense
            selected={m.id === curModel}
            onClick={() => { setOv({ ...ov, model: m.id });
                             setMAnchor(null); }}>
            {m.id}
          </MenuItem>))}
      </Menu>
    </Box>
  );

  const submitDiscussed = (text, model) =>
    post("/api/tasks", { project: project === "workspace" ? null : project,
                         text, mode: "code",
                         ...(model ? { model } : {}) })
      .then(d => { if (d.ok) { setDiscussOpen(false); onSent?.(); }
                   else toast("Ошибка: " + (d.error || "?")); })
      .catch(e => toast("Сеть: " + e));

  const discuss = (
    <Discuss open={discussOpen} onClose={() => setDiscussOpen(false)}
             project={project} models={models} defModel={curModel}
             onSubmit={submitDiscussed} toast={toast} />
  );

  const sendText = async raw => {
    const s = raw.trim();
    if (!s) return;
    // режим «Начать задачу»: сообщение копится в пачку, в очередь
    // Devin оно попадёт по кнопке «Начать выполнение»
    if (collect) {
      onCollect?.({ text: s, attach: att });
      setText(""); setAtt(null);
      return;
    }
    setBusy(true);
    try {
      const d = await post("/api/tasks", {
        project: project === "workspace" ? null : project, text: s,
        ...(ov.mode ? { mode: ov.mode } : {}),
        ...(ov.ac !== undefined ? { auto_commit: ov.ac } : {}),
        ...(ov.model ? { model: ov.model } : {}),
        ...(att ? { attach: att.id } : {}) });
      if (d.ok) { setText(""); setOv({}); setAtt(null); onSent?.(); }
      else toast("Ошибка: " + (d.error || "?"));
    } catch (e) { toast("Сеть: " + e); }
    setBusy(false);
  };
  // во время записи «В работу» = стоп+распознать: обычный режим —
  // текст в поле (второе нажатие отправит), быстрый — уходит сразу
  const send = () => {
    const r = recRef.current;
    if (r) { stopRec(r); return; }
    sendText(textRef.current);
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
        const merged = (textRef.current
                        ? textRef.current.replace(/\s+$/, "") + " "
                        : "") + d.text.trim();
        if (fast) sendText(merged);          // быстрый: сразу в работу
        else setText(merged);
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

  if (mobile) return (<>
    <Paper elevation={0} sx={{
      position: "fixed", left: 0, right: 0, bottom: 0, zIndex: 10,
      borderRadius: 0, borderTop: "1px solid", borderColor: "divider" }}>
      {chips}
      {fileInput}
      <Box sx={{ px: 1, pt: 0, pb: "5px",
                 display: "flex", alignItems: "flex-end", gap: 0.5 }}>
        <TextField
          multiline minRows={1} maxRows={50} fullWidth size="small"
          sx={{ "& .MuiInputBase-root": { maxHeight: "80vh",
                                          overflowY: "auto" } }}
          placeholder={curMode === "ask"
                            ? `Вопрос по «${project || "…"}»`
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
        <BottomNavigationAction
          label={collect ? "+ В задачу"
                        : (curMode === "ask" ? "Спросить" : "В работу")}
          icon={<SendIcon />}
          onClick={send} disabled={busy || !text.trim()}
          sx={{ minWidth: 0,
                color: text.trim() ? "#fff" : "rgba(255,255,255,.4)" }} />
        <BottomNavigationAction label={fast ? "Быстрый" : "Обычный"}
          icon={fast ? <FlashOnIcon /> : <FlashOffIcon />}
          onClick={() => onFast && onFast(fast ? "0" : "1")}
          disabled={!project}
          sx={{ minWidth: 0,
                color: fast ? "#ffd54f" : "rgba(255,255,255,.72)" }} />
        <BottomNavigationAction label="Файл"
          icon={<AttachFileIcon />}
          onClick={() => fileRef.current?.click()}
          sx={{ minWidth: 0, color: "#fff" }} />
        <BottomNavigationAction label="Обсудить"
          icon={<PsychologyIcon />}
          onClick={() => setDiscussOpen(true)}
          sx={{ minWidth: 0, color: "#fff" }} />
      </BottomNavigation>
    </Paper>
    {discuss}
  </>);

  return (<>
    <Paper elevation={0} sx={{
      position: "fixed", left: 0, right: 0, bottom: 0, zIndex: 10,
      borderRadius: 0, borderTop: "1px solid", borderColor: "divider" }}>
      <Box sx={{ maxWidth: 1280, mx: "auto", px: 1.5 }}>{chips}</Box>
      <Grid container spacing={1} sx={{
        maxWidth: 1280, mx: "auto", px: 1.5, pb: 1.5, pt: 0,
        alignItems: "flex-end" }}>
        <Grid size={{ xs: 12, sm: "grow" }}>
          <Box sx={{ display: "flex", alignItems: "flex-end", gap: 0.5 }}>
            <TextField
            multiline minRows={1} maxRows={50} fullWidth size="small"
            sx={{ "& .MuiInputBase-root": { maxHeight: "80vh",
                                            overflowY: "auto" } }}
            placeholder={(curMode === "ask"
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
          </Box>
        </Grid>
        <Grid size={{ xs: 12, sm: "auto" }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 0.8,
                     justifyContent: "flex-end", flexWrap: "nowrap" }}>
            {fileInput}
            <IconButton size="small" title="прикрепить файл к задаче"
                        onClick={() => fileRef.current?.click()}>
              <AttachFileIcon />
            </IconButton>
            <IconButton size="small" title="обсудить идею с Devin"
                        onClick={() => setDiscussOpen(true)}>
              <PsychologyIcon />
            </IconButton>
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
                    sx={{ whiteSpace: "nowrap", px: 2, minWidth: 0,
                          height: 36, borderRadius: "9px",
                          textTransform: "none", fontWeight: 600,
                          boxShadow: "none",
                          "&:hover": { boxShadow: "none" } }}>
              {collect ? "+ В задачу"
                       : (curMode === "ask" ? "Спросить" : "В работу")}
            </Button>
          </Box>
        </Grid>
      </Grid>
    </Paper>
    {discuss}
  </>);
}
