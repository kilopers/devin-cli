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
import Tooltip from "@mui/material/Tooltip";
import Chip from "@mui/material/Chip";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Typography from "@mui/material/Typography";
import MicIcon from "@mui/icons-material/Mic";
import StopIcon from "@mui/icons-material/Stop";
import MenuIcon from "@mui/icons-material/Menu";
import HourglassEmptyIcon from "@mui/icons-material/HourglassEmpty";
import SendIcon from "@mui/icons-material/Send";
import RefreshIcon from "@mui/icons-material/Refresh";
import AttachFileIcon from "@mui/icons-material/AttachFile";
import CloseIcon from "@mui/icons-material/Close";
import FlashOnIcon from "@mui/icons-material/FlashOn";
import FlashOffIcon from "@mui/icons-material/FlashOff";
import useMediaQuery from "@mui/material/useMediaQuery";
import { api, apiJson as get, post } from "./api.js";
import { STT_RATE, resample, encodeWav, getMicStream } from "./audio.js";

const fmtDur = s => String(Math.floor(s / 60)).padStart(2, "0") + ":" +
                    String(Math.floor(s % 60)).padStart(2, "0");
// распознанный текст длиннее этого порога не вливается в поле,
// а показывается оверлей-карточкой поверх композера — иначе
// многострочный инпут раздувает бар (compH) и сжимает всю доску
const DICT_DRAFT_MIN = 300;

export default function Composer({ project, sttStatus, toast, onSent,
                                   conn, onOpenDrawer, accent, mode, onMode,
                                   chat,
                                   fast, fastOv, onFast, topic,
                                   topicName, topics, mainDef,
                                   note, onNoteDone,
                                   cont, onContDone,
                                   onTopic, onNewTopic, inject }) {
  // <md = phone layout: single bottom-nav bar
  const mobile = useMediaQuery(t => t.breakpoints.down("md"));
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [recInfo, setRecInfo] = useState("");  // timer/status line near the mic
  const recRef = useRef(null);
  const [recording, setRecording] = useState(false);
  const [recognizing, setRecognizing] = useState(false);
  const [lastAudio, setLastAudio] = useState(null);  // failed WAV → retry
  const [dictDraft, setDictDraft] = useState(null);  // длинный диктант → оверлей
  const textRef = useRef("");
  textRef.current = text;

  // диктовка из колонки канбана (🎙 у «＋ … сюда»): распознанный
  // текст приходит пропом inject {text,n} — короткий дописываем
  // в поле, длинный — в оверлей-превью поверх бара (dictDraftEl)
  useEffect(() => {
    if (!inject?.n) return;
    const m = (textRef.current
               ? textRef.current.replace(/\s+$/, "") + " " : "")
              + inject.text;
    if (m.length > DICT_DRAFT_MIN) setDictDraft(m);
    else setText(m);
  }, [inject?.n]);   // eslint-disable-line react-hooks/exhaustive-deps

  // чипы параметров следующей задачи: проектные дефолты + разовые
  // оверрайды (действуют только на ближайшую отправку)
  const [eff, setEff] = useState({ model: "", mode: "code", ac: "0" });
  const [ov, setOv] = useState({});       // {mode?, ac?, model?}
  const [models, setModels] = useState([]);
  const [att, setAtt] = useState(null);     // {id, name} прикреплённый файл
  const fileRef = useRef(null);
  const [mAnchor, setMAnchor] = useState(null);
  const [tAnchor, setTAnchor] = useState(null);   // меню целевой темы
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

  // настройки целевой колонки: её дефолты идут после разовых
  // оверрайдов, но раньше проектных (eff.*)
  const tset = (topic && topic !== "main"
    ? (topics || []).find(t => String(t.id) === topic)
    : mainDef) || {};
  const pick = (...vs) =>
    vs.find(v => v !== undefined && v !== null && v !== "");
  const curMode = pick(ov.mode, tset.reply_mode, eff.mode) || "code";
  const curAc = pick(ov.ac, tset.auto_commit, eff.ac) || "0";
  const curModel = pick(ov.model, tset.model, eff.model) || "";
  // «сказать» — карточка-заметка в колонке (Devin её не получает).
  // Выбранная («нажатая») заметка принудительно включает режим:
  // ввод дописывается в её текст; чипы настроек при say не нужны
  const effMode = note ? "say" : curMode;
  const say = effMode === "say";

  const pickFile = async e => {
    const fl = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!fl) return;
    if (fl.size > 50 * 1024 * 1024) { toast("Файл > 50 МБ"); return; }
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
    <Tooltip title="прикреплённый файл — крестик убирает">
      <Chip size="small" icon={<AttachFileIcon />} label={att.name}
            sx={chipSx} color="primary" variant="outlined"
            onDelete={() => setAtt(null)} />
    </Tooltip>);
  const chips = (
    <Box sx={{ display: "flex", gap: 0.7, flexWrap: "nowrap",
               justifyContent: "flex-start", overflowX: "auto", px: 0.5,
               pt: 1, pb: 0.9,
               "& .MuiChip-root": { flexShrink: 0 },
               "&::-webkit-scrollbar": { display: "none" } }}>
      {attChip}
      {/* целевая колонка канбана: в какую тему упадёт задача */}
      <Tooltip title="тема (колонка доски), в которую упадёт новая задача">
        <Chip size="small" clickable sx={chipSx}
          label={"🧵 " + (topicName || "Главная")}
          color={topic && topic !== "main" ? "primary" : "default"}
          variant={topic && topic !== "main" ? "filled" : "outlined"}
          onClick={e => setTAnchor(e.currentTarget)} />
      </Tooltip>
      <Menu anchorEl={tAnchor} open={!!tAnchor}
            onClose={() => setTAnchor(null)}>
        {/* порядок = как на доске: «Главная» в общем sort */}
        {[
          { key: "main", sort: mainDef?.sort || 0 },
          ...(topics || []).map(t =>
            ({ key: String(t.id), sort: t.sort || t.id })),
        ].sort((a, b) => (a.sort - b.sort)
               || String(a.key).localeCompare(String(b.key)))
         .map(c => c.key === "main" ? (
          <MenuItem key="main" dense
            selected={!topic || topic === "main"}
            sx={{ fontSize: 13 }}
            onClick={() => { onTopic?.("main"); setTAnchor(null); }}>
            {mainDef?.name ? "⭐ " + mainDef.name : "⭐ Главная"}
          </MenuItem>
         ) : (
          <MenuItem key={c.key} dense
            selected={c.key === topic}
            sx={{ fontSize: 13 }}
            onClick={() => { onTopic?.(c.key);
                             setTAnchor(null); }}>
            {(() => { const t = topics.find(
                        x => String(x.id) === c.key) || {};
              return (t.name || `тема #${c.key}`) +
                     (t.has_session ? " · 🔁" : ""); })()}
          </MenuItem>))}
        {onNewTopic && project !== "workspace" &&
          <MenuItem dense sx={{ fontSize: 13, fontWeight: 600,
                                color: "primary.main" }}
            onClick={() => { setTAnchor(null); onNewTopic(); }}>
            ＋ Новая тема
          </MenuItem>}
      </Menu>
      <Tooltip title={note
                ? "карточка выбрана — смена режима отожмёт её"
                : "режим следующей задачи" +
                  (ov.mode ? " — переопределено разово" : "")}>
        <Chip size="small" clickable sx={chipSx}
          label={say ? "📝 Заметка"
                 : effMode === "ask" ? "💬 Спросить"
                 : effMode === "plan" ? "📋 План" : "🛠 Код"}
          color={ov.mode || note ? "primary" : "default"}
          variant={ov.mode || note ? "filled" : "outlined"}
          onClick={() => {
            if (note) { onNoteDone?.();
                        setOv({ ...ov, mode: "code" }); return; }
            setOv({ ...ov,
              mode: curMode === "code" ? "ask"
                    : curMode === "ask" ? "plan"
                    : curMode === "plan" ? "say" : "code" }); }} />
      </Tooltip>
      <Tooltip title={say ? "у заметки не применяется"
                : "коммит после задачи" +
                  (ov.ac ? " — переопределено разово" : "")}>
        <span>
          <Chip size="small" clickable={!say} disabled={say} sx={chipSx}
            label={curAc === "1" ? "Автокоммит" : "Ручной коммит"}
            color={ov.ac ? "primary" : "default"}
            variant={ov.ac ? "filled" : "outlined"}
            onClick={() => setOv({ ...ov,
              ac: curAc === "1" ? "0" : "1" })} />
        </span>
      </Tooltip>
      <Tooltip title={say ? "у заметки не применяется"
                : "модель следующей задачи" +
                  (ov.model ? " — переопределено разово" : "")}>
        <span>
          <Chip size="small" clickable={!say} disabled={say} sx={chipSx}
            label={"Модель: " + (curModel || "—")}
            color={ov.model ? "primary" : "default"}
            variant={ov.model ? "filled" : "outlined"}
            onClick={e => setMAnchor(e.currentTarget)} />
        </span>
      </Tooltip>
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
      <Tooltip title={say ? "у заметки не применяется"
                : "быстрый режим — голосовая задача без " +
                  "подтверждения" +
                  (fastOv ? " — переопределено разово" : "")}>
        <span>
          <Chip size="small" clickable={!say} disabled={say} sx={chipSx}
            label={fast ? "⚡ Быстрый" : "Обычный"}
            color={fastOv ? "primary" : "default"}
            variant={fastOv ? "filled" : "outlined"}
            onClick={() => onFast?.()} />
        </span>
      </Tooltip>
      {note &&
        <Tooltip title={"ввод допишется в выбранную карточку — " +
                        "крестик отжимает её"}>
          <Chip size="small" color="primary" variant="outlined"
            sx={chipSx}
            label={"✎ " +
                   (((note.prompt || "").trim().split("\n")[0] || "")
                    .slice(0, 42) || "карточка") + "…"}
            onDelete={() => onNoteDone?.()} />
        </Tooltip>}
      {cont &&
        <Tooltip title={"ввод — доделка выбранной карточки: уйдёт " +
                        "обратно в работу той же сессией; крестик " +
                        "отжимает её"}>
          <Chip size="small" color="primary" variant="outlined"
            sx={chipSx}
            label={"↩ " +
                   (((cont.prompt || "").trim().split("\n")[0] || "")
                    .slice(0, 42) || "карточка") + "…"}
            onDelete={() => onContDone?.()} />
        </Tooltip>}
    </Box>
  );

  const sendText = async raw => {
    const s = raw.trim();
    if (!s) return;
    setBusy(true);
    try {
      if (cont) {
        // «↻ продолжить» на done-карточке: текст дописывается в её
        // prompt (POST /api/task/continue), задача уходит обратно в
        // queued и выполняется той же сессией темы — карточка
        // отжимается сама, когда опрос привезёт новый статус
        const d = await post("/api/task/continue",
                             { stem: cont.stem, text: s });
        if (d.ok) { setText(""); onSent?.(); }
        else toast("Ошибка: " + (d.error || "?"));
      } else if (note) {
        // «нажатая» карточка-заметка: ввод дописывается в её текст
        // (POST /api/task/append, статус остаётся note) и она сразу
        // отжимается
        const d = await post("/api/task/append",
                             { stem: note.stem, text: s });
        if (d.ok) { setText(""); onNoteDone?.(); onSent?.(); }
        else toast("Ошибка: " + (d.error || "?"));
      } else {
        const d = await post("/api/tasks", {
          project: project === "workspace" ? null : project, text: s,
          topic: topic || "main",
          ...(say || ov.mode ? { mode: say ? "say" : ov.mode } : {}),
          ...(ov.ac !== undefined ? { auto_commit: ov.ac } : {}),
          ...(ov.model ? { model: ov.model } : {}),
          ...(att ? { attach: att.id } : {}) });
        if (d.ok) { setText(""); setOv({}); setAtt(null); onSent?.(); }
        else toast("Ошибка: " + (d.error || "?"));
      }
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
        else if (merged.length > DICT_DRAFT_MIN)
          setDictDraft(merged);              // длинное — оверлей-превью
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
      const stream = await getMicStream();
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

  // превью длинного надиктованного текста: карточка поверх бара
  // (absolute внутри fixed #composer-bar — в потоке не участвует,
  // compH и доска не прыгают). «✎ в поле» — осознанно влить в
  // инпут для правки; «Отправить» — тот же sendText, что и у
  // обычной отправки (note/cont/режим/вложение учитываются)
  const dictDraftEl = dictDraft && (
    <Paper elevation={0} sx={{
      position: "absolute", left: { xs: 8, md: 16 },
      right: { xs: 8, md: 16 }, bottom: 0, zIndex: 5,
      borderRadius: "12px", border: "1px solid",
      borderColor: "divider", bgcolor: "background.paper",
      boxShadow: "0 -8px 24px rgba(28,33,40,.14)",
      p: 1.2, display: "flex", flexDirection: "column", gap: 1 }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 0.8 }}>
        <MicIcon sx={{ fontSize: 15, color: "info.main" }} />
        <Typography variant="caption" color="text.secondary"
                    sx={{ fontSize: 11.5, flex: 1 }}>
          распознанный текст · {dictDraft.length} зн.
        </Typography>
        <Tooltip title="отбросить — текст в поле не трогаем">
          <IconButton size="small" onClick={() => setDictDraft(null)}>
            <CloseIcon sx={{ fontSize: 15 }} />
          </IconButton>
        </Tooltip>
      </Box>
      <Typography variant="body2" sx={{
        fontSize: 13, whiteSpace: "pre-wrap", wordBreak: "break-word",
        maxHeight: "45vh", overflowY: "auto" }}>
        {dictDraft}
      </Typography>
      <Box sx={{ display: "flex", gap: 0.8,
                 justifyContent: "flex-end" }}>
        <Button size="small" variant="outlined"
                onClick={() => { setText(dictDraft);
                                 setDictDraft(null); }}
                sx={{ textTransform: "none", fontSize: 12,
                      borderRadius: "9px" }}>
          ✎ в поле
        </Button>
        <Button size="small" variant="contained" disableElevation
                disabled={busy}
                onClick={() => { const t = dictDraft;
                                 setDictDraft(null); sendText(t); }}
                sx={{ textTransform: "none", fontSize: 12,
                      borderRadius: "9px" }}>
          {say ? "Сохранить"
              : curMode === "ask" ? "Спросить"
              : curMode === "plan" ? "План" : "Отправить"}
        </Button>
      </Box>
    </Paper>);

  if (mobile) return (<>
    <Paper elevation={0} id="composer-bar" sx={{
      position: "fixed", left: 0, right: 0, bottom: 0, zIndex: 10,
      borderRadius: 0, borderTop: "1px solid", borderColor: "divider" }}>
      {chips}
      {fileInput}
      <Box sx={{ px: 1, pt: 0, pb: "5px",
                 display: "flex", alignItems: "flex-end", gap: 0.5 }}>
        <TextField
          id="composer-input"
          multiline minRows={1} maxRows={50} fullWidth size="small"
          sx={{ "& .MuiInputBase-root": { maxHeight: "80vh",
                                          overflowY: "auto" } }}
          placeholder={cont ? "Доделать в этой карточке…"
                            : chat ? "Спросить…"
                            : say
                            ? (note ? "Дописать в карточку…"
                                    : "Заметка в колонку…")
                            : curMode === "ask"
                            ? `Вопрос по «${project || "…"}»`
                            : curMode === "plan"
                            ? `Что спланировать по «${project || "…"}»`
                            : `Задача для «${project || "…"}»`}
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault(); send();
            }
          }}
          sx={{ "& .MuiOutlinedInput-root": { borderRadius: "12px" } }} />
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
          icon={recording ? <StopIcon />
            : recognizing ? <HourglassEmptyIcon /> : <MicIcon />}
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
          label={say ? "Сохранить"
                 : curMode === "ask" ? "Спросить"
                 : curMode === "plan" ? "План" : "Делай"}
          icon={<SendIcon />}
          onClick={send} disabled={busy || !text.trim()}
          sx={{ minWidth: 0,
                color: text.trim() ? "#fff" : "rgba(255,255,255,.4)" }} />
        <BottomNavigationAction label={fast ? "Быстрый" : "Обычный"}
          icon={fast ? <FlashOnIcon /> : <FlashOffIcon />}
          onClick={() => onFast && onFast()}
          disabled={!project}
          sx={{ minWidth: 0,
                color: fast ? "#ffd54f" : "rgba(255,255,255,.72)" }} />
        <BottomNavigationAction label="Файл"
          icon={<AttachFileIcon />}
          onClick={() => fileRef.current?.click()}
          sx={{ minWidth: 0, color: "#fff" }} />
      </BottomNavigation>
      {dictDraftEl}
    </Paper>
  </>);

  return (<>
    <Paper elevation={0} id="composer-bar" sx={{
      position: "fixed", left: 0, right: 0, bottom: 0, zIndex: 10,
      borderRadius: 0, borderTop: "1px solid", borderColor: "divider" }}>
      <Box sx={{ px: 1.5 }}>{chips}</Box>
      <Grid container spacing={1} sx={{
        px: 1.5, pb: 1.5, pt: 0,
        alignItems: "flex-end" }}>
        <Grid size={{ xs: 12, sm: "grow" }}>
          <Box sx={{ display: "flex", alignItems: "flex-end", gap: 0.5 }}>
            <TextField
            id="composer-input"
            multiline minRows={1} maxRows={50} fullWidth size="small"
            sx={{ "& .MuiInputBase-root": { maxHeight: "80vh",
                                            overflowY: "auto" } }}
            placeholder={(cont ? "Доделать в этой карточке — тот же текст, та же сессия"
             : say
             ? (note ? "Дописать в карточку…"
                     : "Заметка в колонку — агент её не получит")
             : curMode === "ask"
             ? `Вопрос по «${project || "…"}»`
             : curMode === "plan"
             ? `Что спланировать по «${project || "…"}»`
             : `Задача для агента по проекту «${project || "…"}»`) +
                         " — Ctrl+Enter чтобы отправить"}
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault(); send();
              }
            }}
            sx={{ "& .MuiOutlinedInput-root": { borderRadius: "12px" } }} />
          </Box>
        </Grid>
        <Grid size={{ xs: 12, sm: "auto" }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 0.8,
                     justifyContent: "flex-end", flexWrap: "nowrap" }}>
            {fileInput}
            <Tooltip title="прикрепить файл к задаче">
              <IconButton size="small"
                          onClick={() => fileRef.current?.click()}>
                <AttachFileIcon />
              </IconButton>
            </Tooltip>
            <Tooltip title={recognizing ? "распознаю запись…"
                            : recording ? "остановить запись"
                            : "надиктовать голосом"}>
              <IconButton onClick={micClick} size="small"
                          color={recording ? "error" : "default"}
                          sx={recording
                            ? { animation: "pulse 1s infinite",
                                "@keyframes pulse":
                                  { "50%": { opacity: 0.35 } } }
                            : {}}>
                {recording ? <StopIcon />
                  : recognizing ? <HourglassEmptyIcon /> : <MicIcon />}
              </IconButton>
            </Tooltip>
            {lastAudio && !recognizing && (
              <Tooltip title="отправить запись на распознавание ещё раз">
                <Button size="small" variant="outlined" color="warning"
                        startIcon={<RefreshIcon sx={{ fontSize: 15 }} />}
                        onClick={() => sendAudio(lastAudio)}
                        sx={{ textTransform: "none", whiteSpace: "nowrap",
                              fontSize: 12, px: 1, minWidth: 0 }}>
                  ещё раз
                </Button>
              </Tooltip>
            )}
            <Tooltip title="счётчик символов / статус диктовки">
              <Typography variant="caption" color="text.secondary"
                          sx={{ minWidth: 38, whiteSpace: "nowrap",
                                textAlign: "center" }}>
                {shownStat}
              </Typography>
            </Tooltip>
            <Tooltip title="отправить — Ctrl+Enter">
              <span>
                <Button variant="contained" size="small" onClick={send}
                    disabled={busy} endIcon={<SendIcon sx={{fontSize: 15}} />}
                    sx={{ whiteSpace: "nowrap", px: 2, minWidth: 0,
                          height: 36, borderRadius: "9px",
                          textTransform: "none", fontWeight: 600,
                          boxShadow: "none",
                          "&:hover": { boxShadow: "none" } }}>
                  {say ? "Сохранить"
                       : curMode === "ask" ? "Спросить"
                       : curMode === "plan" ? "Спланировать" : "В работу"}
                </Button>
              </span>
            </Tooltip>
          </Box>
        </Grid>
      </Grid>
      {dictDraftEl}
    </Paper>
  </>);
}
