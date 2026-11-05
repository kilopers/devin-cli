// Настройки темы (колонки канбана): название, цвет колонки из палитры
// светлых цветов и дефолты её задач — модель, режим, автокоммит,
// быстрый режим. «по умолчанию» = наследовать из настроек проекта.
// Открывается из меню ⋯ колонки и по «＋ Новая тема» (режим create).
import { useEffect, useState } from "react";
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button,
  Stack, Typography, TextField, MenuItem, Box, Tooltip,
} from "@mui/material";
import { apiJson as get, post } from "./api.js";

// светлые тона — тёмная шапка и белые карточки читаются на них хорошо
export const TOPIC_COLORS = [
  "#eceffc", "#e3f2fd", "#e0f7fa", "#e0f2f1",
  "#e8f5e9", "#f1f8e9", "#fffde7", "#fff3e0",
  "#fbe9e7", "#fce4ec", "#f3e5f5", "#eceff1",
];

export default function TopicSettings({ project, dlg, onClose, onSaved,
                                       toast }) {
  // dlg: {kind:"create"} | {kind:"edit", topic} | {kind:"main", current}
  const [name, setName] = useState("");
  const [color, setColor] = useState("");
  const [model, setModel] = useState("");
  const [mode, setMode] = useState("");
  const [ac, setAc] = useState("");
  const [fast, setFast] = useState("");
  const [models, setModels] = useState([]);
  const [busy, setBusy] = useState(false);

  const isCreate = dlg?.kind === "create";
  const isMain = dlg?.kind === "main";
  useEffect(() => {
    if (!dlg) return;
    const src = dlg.kind === "edit" ? (dlg.topic || {})
              : dlg.kind === "main" ? (dlg.current || {}) : {};
    setName(dlg.kind === "edit" ? (dlg.topic?.name || "") : "");
    setColor(src.color || "");
    setModel(src.model || "");
    setMode(src.reply_mode || "");
    setAc(src.auto_commit || "");
    setFast(src.fast || "");
    get("/api/models").then(j => setModels(j.models || []))
      .catch(() => {});
  }, [dlg]);

  const save = async () => {
    setBusy(true);
    try {
      const body = { project, color, model, reply_mode: mode,
                     auto_commit: ac, fast };
      const d = await post("/api/topics",
        isCreate ? { ...body, action: "create", name: name.trim() }
        : isMain ? { ...body, action: "settings", main: true }
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
         : isMain ? "Настройки: ⭐ Главная"
         : `Настройки: ${dlg?.topic?.name || "тема #" + dlg?.topic?.id}`}
      </DialogTitle>
      <DialogContent>
        <Typography variant="caption" color="text.secondary">
          Задачи этой колонки получают эти настройки; пустые значения
          наследуются из настроек проекта.
        </Typography>
        <Stack spacing={2} sx={{ mt: 1.5 }}>
          {!isMain &&
            <TextField label="Название темы" size="small" fullWidth
                       value={name}
                       onChange={e => setName(e.target.value)}
                       helperText={isCreate
                         ? "пусто — агент назовёт по первой задаче"
                         : ""} />}
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
          <TextField select label="Модель" size="small" fullWidth
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
                     helperText="пусто — режим проекта/настроек">
            <MenuItem value="">— по умолчанию —</MenuItem>
            <MenuItem value="code">🛠 код</MenuItem>
            <MenuItem value="ask">💬 вопрос</MenuItem>
          </TextField>
          <TextField select label="Автокоммит" size="small" fullWidth
                     value={ac}
                     onChange={e => setAc(e.target.value)}
                     helperText="коммит + push после задачи">
            <MenuItem value="">— по умолчанию —</MenuItem>
            <MenuItem value="1">⚡ автокоммит</MenuItem>
            <MenuItem value="0">✋ вручную</MenuItem>
          </TextField>
          <TextField select label="Быстрый режим" size="small" fullWidth
                     value={fast}
                     onChange={e => setFast(e.target.value)}
                     helperText="голосовая задача без подтверждения">
            <MenuItem value="">— по умолчанию —</MenuItem>
            <MenuItem value="1">⚡ быстрый</MenuItem>
            <MenuItem value="0">обычный</MenuItem>
          </TextField>
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
