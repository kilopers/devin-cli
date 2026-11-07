// Настройки темы (колонки канбана): название, цвет колонки из палитры
// светлых цветов и дефолты её задач — модель, режим, автокоммит,
// быстрый режим. «по умолчанию» = наследовать из настроек проекта.
// Открывается из меню ⋯ колонки и по «＋ Новая тема» (режим create).
import { useEffect, useState } from "react";
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button,
  Stack, Typography, TextField, MenuItem, Box, Tooltip,
  Checkbox, FormControlLabel,
} from "@mui/material";
import { apiJson as get, post } from "./api.js";

// светлые тона — тёмная шапка и белые карточки читаются на них хорошо;
// второй ряд — те же оттенки чуть насыщеннее (Material 100)
export const TOPIC_COLORS = [
  "#eceffc", "#e3f2fd", "#e0f7fa", "#e0f2f1",
  "#e8f5e9", "#f1f8e9", "#fffde7", "#fff3e0",
  "#fbe9e7", "#fce4ec", "#f3e5f5", "#eceff1",
  "#c5cae9", "#bbdefb", "#b2ebf2", "#b2dfdb",
  "#c8e6c9", "#dcedc8", "#fff9c4", "#ffe0b2",
  "#ffccbc", "#f8bbd0", "#e1bee7", "#cfd8dc",
];

export default function TopicSettings({ project, dlg, onClose, onSaved,
                                       toast, topics }) {
  // dlg: {kind:"create"} | {kind:"edit", topic} | {kind:"main", current}
  const [name, setName] = useState("");
  const [color, setColor] = useState("");
  const [agent, setAgent] = useState("");   // движок колонки: devin/claude
  const [agents, setAgents] = useState([]); // настроенные из /api/agents
  const [model, setModel] = useState("");
  const [mode, setMode] = useState("");
  const [ac, setAc] = useState("");
  const [fast, setFast] = useState("");
  // чья сессия у темы — только при создании, потом не меняется:
  // "main" — общая сессия проекта (как у «Главной», дефолт),
  // "own" — своя новая, "<id>" — прицепиться к сессии темы
  const [sess, setSess] = useState("main");
  // чат-колонка (диалог-пузыри, своя сессия) — только при создании
  const [chat, setChat] = useState(false);
  const [models, setModels] = useState([]);
  // инструкции колонки: свои custom-инструкции, привязанные к этой
  // теме — работают только в её задачах (к проекту не обязаны
  // быть подключёнными). Все доступные — из /api/instr
  const [instrList, setInstrList] = useState([]);
  const [instrSel, setInstrSel] = useState(() => new Set());
  const [busy, setBusy] = useState(false);

  const isCreate = dlg?.kind === "create";
  const isMain = dlg?.kind === "main";
  useEffect(() => {
    if (!dlg) return;
    const src = dlg.kind === "edit" ? (dlg.topic || {})
              : dlg.kind === "main" ? (dlg.current || {}) : {};
    setName(dlg.kind === "edit" ? (dlg.topic?.name || "")
          : dlg.kind === "main" ? (dlg.current?.name || "") : "");
    setColor(src.color || "");
    setAgent(src.agent || "");
    setModel(src.model || "");
    setMode(src.reply_mode || "");
    setAc(src.auto_commit || "");
    setFast(src.fast || "");
    setSess("main");
    setChat(false);
    setInstrSel(new Set(src.instrs || []));
    get("/api/agents").then(j =>
      setAgents((j.agents || []).filter(a => a.configured)))
      .catch(() => {});
    get("/api/instr?project=" + encodeURIComponent(project || ""))
      .then(j => setInstrList((j.instructions || [])
        .filter(r => r.kind === "custom" && r.mine)))
      .catch(() => setInstrList([]));
  }, [dlg]);

  // каталог моделей — выбранного движка (пусто = движок по умолчанию)
  useEffect(() => {
    if (!dlg) return;
    get("/api/models" + (agent ? "?agent=" + agent : ""))
      .then(j => setModels(j.models || [])).catch(() => {});
  }, [dlg, agent]);

  const save = async () => {
    setBusy(true);
    try {
      const body = { project, color, model, agent, reply_mode: mode,
                     auto_commit: ac, fast, instrs: [...instrSel] };
      const d = await post("/api/topics",
        isCreate ? { ...body, action: "create", name: name.trim(),
                     chat: chat ? 1 : 0,
                     own_session: chat || sess === "own" ? "1" : "0",
                     session_topic_id:
                       sess !== "own" && sess !== "main"
                         ? Number(sess) : null }
        : isMain ? { ...body, action: "settings", main: true,
                     name: name.trim() }
        : { ...body, action: "settings", id: dlg.topic.id,
            name: name.trim() });
      setBusy(false);
      if (d.ok) {
        toast?.(isCreate ? "Тема создана" : "Настройки темы сохранены");
        onSaved?.(d.id);
        onClose();
      } else toast?.("Ошибка: " + (d.error || "?"));
    } catch (e) { setBusy(false); toast?.("Сеть: " + e); }
  };

  const sw = c => ({
    width: 26, height: 26, borderRadius: "8px", cursor: "pointer",
    bgcolor: c || "#fff",
    border: "2px solid",
    borderColor: color === c ? "#5e6ad2" : "rgba(28,33,40,.12)",
    boxSizing: "border-box", flexShrink: 0,
    transition: "border-color .15s, transform .15s",
    "&:hover": { transform: "scale(1.12)" },
  });

  return (
    <Dialog open={!!dlg} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle sx={{ fontSize: 16 }}>
        {isCreate ? "＋ Новая тема"
         : isMain ? "Настройки: " + (dlg?.current?.name
                     ? "⭐ " + dlg.current.name : "⭐ Главная")
         : `Настройки: ${dlg?.topic?.name || "тема #" + dlg?.topic?.id}`}
      </DialogTitle>
      <DialogContent>
        <Typography variant="caption" color="text.secondary">
          Задачи этой колонки получают эти настройки; пустые значения
          наследуются из настроек проекта.
        </Typography>
        <Stack spacing={2} sx={{ mt: 1.5 }}>
          <TextField label={isMain ? "Название колонки"
                                   : "Название темы"}
                     size="small" fullWidth
                     value={name}
                     onChange={e => setName(e.target.value)}
                     helperText={isCreate
                       ? "пусто — агент назовёт по первой задаче"
                       : isMain ? "пусто — «Главная»" : ""} />
          {isCreate &&
            <FormControlLabel
              control={<Checkbox checked={chat}
                       onChange={e => setChat(e.target.checked)} />}
              label={"💬 Диалог — чат-колонка: сообщения пузырями " +
                     "из общего поля ввода, своя сессия; тип " +
                     "потом не поменять"} />}
          {isCreate && !chat &&
            <TextField select label="Сессия" size="small" fullWidth
                       value={sess}
                       onChange={e => setSess(e.target.value)}
                       helperText="задаётся при создании, изменить нельзя">
              <MenuItem value="main">
                ⭐ общая — как у «Главной»
              </MenuItem>
              <MenuItem value="own">
                🔁 новая сессия — у темы своя
              </MenuItem>
              {(topics || []).filter(t => t.own_session).map(t => (
                <MenuItem key={t.id} value={String(t.id)}>
                  🧵 как у темы «{t.name || "тема #" + t.id}»
                </MenuItem>))}
            </TextField>}
          {dlg?.kind === "edit" && dlg.topic?.chat &&
            <Typography variant="caption" color="primary">
              💬 диалог — чат-колонка (тип задаётся при создании)
            </Typography>}
          {dlg?.kind === "edit" &&
            <Typography variant="caption" color="text.secondary">
              Сессия: {dlg.topic?.own_session
                ? "своя — резюмируется между задачами темы"
                : dlg.topic?.session_topic_id
                  ? "как у темы «" +
                    (dlg.topic.attach_name
                      || "тема #" + dlg.topic.session_topic_id) + "»"
                  : "общая — задачи идут в сессии проекта"}
              {" (задаётся при создании)"}
            </Typography>}
          <Box>
            <Typography variant="caption" color="text.secondary">
              Цвет колонки
            </Typography>
            <Box sx={{ display: "flex", gap: 0.8, flexWrap: "wrap",
                       mt: 0.8 }}>
              <Tooltip title="без цвета">
                <Box onClick={() => setColor("")}
                     sx={{ ...sw(""), borderStyle: "dashed",
                           background:
                             "linear-gradient(135deg, transparent 44%," +
                             " rgba(28,33,40,.35) 46%," +
                             " rgba(28,33,40,.35) 54%, transparent 56%)" }} />
              </Tooltip>
              {TOPIC_COLORS.map(c => (
                <Tooltip key={c} title={c}>
                  <Box onClick={() => setColor(c)} sx={sw(c)} />
                </Tooltip>))}
            </Box>
          </Box>
          {agents.length > 0 &&
            <TextField select label="Агент" size="small" fullWidth
                       disabled={mode === "say"}
                       value={agent}
                       onChange={e => { setAgent(e.target.value);
                                        setModel(""); }}
                       helperText="движок задач колонки; модели — по нему">
              <MenuItem value="">— по умолчанию —</MenuItem>
              {agents.map(a => (
                <MenuItem key={a.key} value={a.key}>
                  {a.key === "claude" ? "🟣 " : "🔷 "}{a.label}
                </MenuItem>))}
            </TextField>}
          <TextField select label="Модель" size="small" fullWidth
                     disabled={mode === "say"}
                     value={model}
                     onChange={e => setModel(e.target.value)}
                     helperText="пусто — модель проекта/настроек">
            <MenuItem value="">— по умолчанию —</MenuItem>
            {models.map(m => (
              <MenuItem key={m.id} value={m.id}>{m.id}</MenuItem>))}
          </TextField>
          <TextField select label="Режим ответа" size="small" fullWidth
                     value={mode}
                     onChange={e => setMode(e.target.value)}
                     helperText={mode === "say"
                       ? "карточки-заметки — агент их не получает"
                       : "пусто — режим проекта/настроек"}>
            <MenuItem value="">— по умолчанию —</MenuItem>
            <MenuItem value="say">📝 заметка</MenuItem>
            <MenuItem value="code">🛠 код</MenuItem>
            <MenuItem value="ask">💬 вопрос</MenuItem>
            <MenuItem value="plan">📋 план</MenuItem>
          </TextField>
          <TextField select label="Автокоммит" size="small" fullWidth
                     disabled={mode === "say"}
                     value={ac}
                     onChange={e => setAc(e.target.value)}
                     helperText="коммит + push после задачи">
            <MenuItem value="">— по умолчанию —</MenuItem>
            <MenuItem value="1">⚡ автокоммит</MenuItem>
            <MenuItem value="0">✋ вручную</MenuItem>
          </TextField>
          <TextField select label="Быстрый режим" size="small" fullWidth
                     disabled={mode === "say"}
                     value={fast}
                     onChange={e => setFast(e.target.value)}
                     helperText="голосовая задача без подтверждения">
            <MenuItem value="">— по умолчанию —</MenuItem>
            <MenuItem value="1">⚡ быстрый</MenuItem>
            <MenuItem value="0">обычный</MenuItem>
          </TextField>
          {instrList.length > 0 &&
            <Box>
              <Typography variant="caption" color="text.secondary">
                Инструкции колонки — действуют только в задачах
                этой темы (к проекту подключены быть не обязаны)
              </Typography>
              <Box sx={{ mt: 0.3 }}>
                {instrList.map(r => (
                  <FormControlLabel key={r.id} sx={{ display: "flex",
                    m: 0 }}
                    control={<Checkbox size="small" sx={{ p: 0.4 }}
                      checked={instrSel.has(r.id)}
                      onChange={e => {
                        const s = new Set(instrSel);
                        if (e.target.checked) s.add(r.id);
                        else s.delete(r.id);
                        setInstrSel(s); }} />}
                    label={<Typography sx={{ fontSize: 12.5 }}>
                             {r.name}</Typography>} />))}
              </Box>
            </Box>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Отмена</Button>
        <Button variant="contained" onClick={save} disabled={busy}>
          {isCreate ? "Создать" : "Сохранить"}</Button>
      </DialogActions>
    </Dialog>
  );
}
