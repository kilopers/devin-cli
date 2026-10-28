// «Обсудить»: черновой диалог — набрасываешь идею (текстом или голосом),
// Gemini формализует её в постановку задачи (полная версия на каждый
// ответ), можно договаривать; «В работу» ставит последнюю постановку
// как обычную задачу на выбранной модели. Чипов режима/автокоммита нет.
import { memo, useEffect, useRef, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Select from "@mui/material/Select";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import CloseIcon from "@mui/icons-material/Close";
import MicIcon from "@mui/icons-material/Mic";
import HourglassEmptyIcon from "@mui/icons-material/HourglassEmpty";
import SendIcon from "@mui/icons-material/Send";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import useMediaQuery from "@mui/material/useMediaQuery";
import { api, apiJson as get, post } from "./api.js";
import Markdown from "./Markdown.jsx";
import { STT_RATE, resample, encodeWav } from "./audio.js";

const MsgRow = memo(function MsgRow({ m }) {
  return m.role === "user" ? (
    <Box sx={{ display: "flex", justifyContent: "flex-end", mb: 1 }}>
      <Paper sx={{ px: 1.5, py: 0.8, maxWidth: "80%",
                   bgcolor: "primary.main", color: "#fff",
                   borderRadius: "12px 12px 2px 12px" }}>
        <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
          {m.text}
        </Typography>
      </Paper>
    </Box>
  ) : (
    <Paper variant="outlined" sx={{ px: 1.5, py: 0.5, mb: 1 }}>
      <Markdown text={m.text} />
    </Paper>
  );
});

export default function Discuss({ open, onClose, project, models,
                                  defModel, onSubmit, toast }) {
  const mobile = useMediaQuery(t => t.breakpoints.down("md"));
  const [msgs, setMsgs] = useState([]);       // {role:"user"|"assistant", text}
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [tail, setTail] = useState("");      // что сейчас делает devin
  const [model, setModel] = useState("");
  const [recInfo, setRecInfo] = useState("");
  const [recording, setRecording] = useState(false);
  const [recognizing, setRecognizing] = useState(false);
  const recRef = useRef(null);
  const listRef = useRef(null);
  const missRef = useRef(0);               // опросы без job (рестарт?)

  useEffect(() => { if (open) setModel(defModel || ""); },
           [open, defModel]);
  // история живёт на сервере (kv) — продолжается на любом устройстве;
  // смена проекта → грузим его обсуждение
  useEffect(() => {
    if (!open) return;
    setMsgs([]); setInput("");
    get("/api/discuss?project=" + encodeURIComponent(project || ""))
      .then(d => {
        if (!d.ok) return;
        setMsgs(d.history || []);
        // сессия могла идти, пока диалог был закрыт (или с другого
        // устройства) — подхватываем опрос
        if (d.job && d.job.status === "running") {
          setBusy(true); setElapsed(d.job.elapsed); setTail(d.job.tail);
        }
      })
      .catch(() => {});
  }, [project, open]);

  const clearDiscuss = () => {
    setMsgs([]); setInput("");
    post("/api/discuss", { action: "clear", project }).catch(() => {});
  };
  useEffect(() => {                       // автопрокрутка к новому
    listRef.current?.scrollTo(0, listRef.current.scrollHeight);
  }, [msgs, busy]);
  // живой статус: devin-сессия идёт в фоне на воркере — опрашиваем
  // каждые 3с: elapsed, хвост вывода (что делает), done/error
  useEffect(() => {
    if (!busy) return;
    let dead = false;
    const poll = () => {
      get("/api/discuss?project=" + encodeURIComponent(project || ""))
        .then(d => {
          if (dead || !d.ok) return;
          const j = d.job;
          if (!j) {                          // воркер перезапустился?
            if (++missRef.current >= 3) {
              setBusy(false); setTail("");
              toast("Сессия потеряна — отправь сообщение ещё раз");
            }
            return;
          }
          missRef.current = 0;
          setElapsed(j.elapsed); setTail(j.tail || "");
          if (j.status === "done") {
            setMsgs(d.history || []); setBusy(false); setTail("");
          } else if (j.status === "error") {
            setBusy(false); setTail("");
            toast("Devin: " + (j.error || "ошибка"));
          }
        })
        .catch(() => {});
    };
    const t = setInterval(poll, 3000);
    poll();
    return () => { dead = true; clearInterval(t); };
  }, [busy, project]);

  const lastPlan = [...msgs].reverse().find(m => m.role === "assistant");

  const send = async () => {
    const s = input.trim();
    if (!s || busy) return;
    const hist = [...msgs, { role: "user", text: s }];
    setMsgs(hist); setInput(""); setBusy(true); setElapsed(0);
    try {
      // сессия в фоне: ok → крутим busy и опрашиваем статус (эффект выше)
      const d = await post("/api/discuss", { history: hist,
                                            project });
      if (!d.ok) {
        toast("Ошибка: " + (d.error || "?"));
        if (!(d.error || "").includes("ещё отвечает")) setBusy(false);
      }
    } catch (e) { toast("Сеть: " + e); setBusy(false); }
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
    setRecognizing(true); setRecInfo("распознаю…");
    try {
      const d = await (await api("/api/stt", { method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: wav })).json();
      if (d.ok && d.text.trim())
        setInput(t => (t ? t.replace(/\s+$/, "") + " " : "")
                      + d.text.trim());
      else toast(d.ok ? "Ничего не распознано"
                      : "STT: " + (d.error || "?"));
    } catch (e) { toast("STT сеть: " + e); }
    setRecognizing(false); setRecInfo("");
  };

  const micClick = async () => {
    const r = recRef.current;
    if (r) { stopRec(r); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia(
        { audio: true });
      const ctx = new (window.AudioContext || window.webkitAudioContext)(
        { sampleRate: STT_RATE });
      const src = ctx.createMediaStreamSource(stream);
      const proc = ctx.createScriptProcessor(4096, 1, 1);
      const gain = ctx.createGain(); gain.gain.value = 0;
      const chunks = [];
      proc.onaudioprocess = e =>
        chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      src.connect(proc); proc.connect(gain); gain.connect(ctx.destination);
      const t0 = Date.now();
      recRef.current = { ctx, proc, src, gain, stream, chunks,
        clock: setInterval(() => setRecInfo(
          String(Math.floor((Date.now() - t0) / 60000)).padStart(2, "0")
          + ":" + String(Math.floor((Date.now() - t0) / 1000) % 60)
                 .padStart(2, "0")), 250),
        timer: setTimeout(() => recRef.current && micClick(), 300000) };
      setRecording(true); setRecInfo("00:00");
    } catch (e) { toast("Микрофон: " + e); }
  };

  return (
    <Dialog open={open} onClose={onClose} fullScreen={mobile}
            fullWidth maxWidth="md"
            PaperProps={{ sx: { height: mobile ? "100%" : "85vh",
                                display: "flex", flexDirection: "column" } }}>
      <Box sx={{ display: "flex", alignItems: "center", px: 1.5, py: 1,
                 borderBottom: 1, borderColor: "divider" }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
          💭 Обсудить задачу{project ? ` — «${project}»` : ""}
        </Typography>
        <Button size="small" variant="outlined"
                disabled={!msgs.length || busy}
                onClick={clearDiscuss}
                sx={{ ml: "auto", textTransform: "none", mr: 0.5,
                      fontSize: 12 }}>
          Новое обсуждение
        </Button>
        <IconButton size="small" onClick={onClose}
                    title="закрыть"><CloseIcon /></IconButton>
      </Box>

      <Box ref={listRef} sx={{ flex: 1, overflowY: "auto", px: 1.5, py: 1 }}>
        {!msgs.length && (
          <Typography color="text.secondary" align="center" sx={{ mt: 6 }}>
            Набросай идею текстом или голосом — Devin оформит её
            в постановку задачи.
          </Typography>)}
        {msgs.map((m, i) => <MsgRow key={i} m={m} />)}
        {busy && (
          <Box sx={{ mb: 1 }}>
            <Typography variant="caption" color="text.secondary"
                        sx={{ display: "block" }}>
              Devin работает… {Math.floor(elapsed / 60)}:
              {String(elapsed % 60).padStart(2, "0")} — процесс жив,
              может занять несколько минут
            </Typography>
            {!!tail && (
              <Typography variant="caption" color="text.secondary"
                          sx={{ display: "block", opacity: .75,
                                fontStyle: "italic" }}>
                сейчас: {tail}
              </Typography>)}
          </Box>)}
      </Box>

      <Box sx={{ px: 1.5, pt: 0.5, pb: 1, borderTop: 1,
                 borderColor: "divider" }}>
        <Box sx={{ display: "flex", alignItems: "flex-end", gap: 0.5 }}>
          <TextField multiline minRows={1} maxRows={8} fullWidth size="small"
            placeholder="Начните говорить…"
            value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault(); send();
              } }}
            sx={{ "& .MuiOutlinedInput-root": { borderRadius: 2 } }} />
          <IconButton size="small" onClick={micClick}
                      color={recording ? "error" : "default"}
                      title="надиктовать"
                      sx={recording ? { animation: "pulse 1s infinite",
                            "@keyframes pulse": { "50%": { opacity: .35 } } }
                                   : {}}>
            {recognizing ? <HourglassEmptyIcon /> : <MicIcon />}
          </IconButton>
          <IconButton size="small" onClick={send}
                      disabled={busy || !input.trim()} title="отправить">
            <SendIcon />
          </IconButton>
        </Box>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1,
                   mt: 0.8 }}>
          <Typography variant="caption" color="text.secondary"
                      sx={{ minWidth: 40 }}>{recInfo}</Typography>
          <Select size="small" value={model} displayEmpty
                  onChange={e => setModel(e.target.value)}
                  sx={{ height: 30, fontSize: 12.5, ml: "auto" }}>
            {(models.length ? models : [{ id: model }]).map(m =>
              <MenuItem key={m.id} value={m.id}>{m.id}</MenuItem>)}
          </Select>
          <Button variant="contained" size="small"
                  disabled={!lastPlan}
                  startIcon={<PlayArrowIcon sx={{ fontSize: 16 }} />}
                  onClick={() => onSubmit(lastPlan.text, model)}
                  sx={{ textTransform: "none", whiteSpace: "nowrap" }}>
            В работу
          </Button>
        </Box>
      </Box>
    </Dialog>
  );
}
