// Настройки конкретного проекта — шестерёнка в селекте проектов.
// Пустая модель/режим = наследовать из настроек юзера;
// автокоммит по умолчанию ВЫКЛ.
import { useEffect, useState } from "react";
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button,
  Stack, Typography, TextField, MenuItem, Alert,
  FormControlLabel, Checkbox,
} from "@mui/material";
import { apiJson as get, post } from "./api.js";

export default function ProjectSettings({ project, onClose, toast,
                                          onDeleted }) {
  const [model, setModel] = useState("");
  const [askDel, setAskDel] = useState(false);
  const [mode, setMode] = useState("");
  const [autoCommit, setAutoCommit] = useState(false);
  const [mainBranch, setMainBranch] = useState("");
  const [branches, setBranches] = useState([]);
  const [models, setModels] = useState([]);
  const [busy, setBusy] = useState(false);
  const [mcp, setMcp] = useState("");

  useEffect(() => {
    if (!project) return;
    get("/api/project/settings?project=" + encodeURIComponent(project))
      .then(j => { setModel(j.model || ""); setMode(j.reply_mode || "");
                   setAutoCommit(j.auto_commit === "1");
                   setMainBranch(j.main_branch || "");
                   setMcp(j.mcp || ""); });
    get("/api/models").then(j => setModels(j.models || []));
    get("/api/branches?project=" + encodeURIComponent(project))
      .then(j => setBranches((j.branches || []).map(b => b.name)));
  }, [project]);

  const save = async () => {
    setBusy(true);
    const j = await post("/api/project/settings", {
      project, model, reply_mode: mode,
      auto_commit: autoCommit ? "1" : "0",
      main_branch: mainBranch.trim(), mcp: mcp.trim() });
    setBusy(false);
    if (j.ok) { toast?.("Настройки проекта сохранены"); onClose(); }
  };

  const del = async () => {
    setBusy(true);
    try {
      const j = await post("/api/project/delete", { project });
      setBusy(false); setAskDel(false);
      if (j.ok) { toast?.("Проект удалён"); onDeleted?.(); onClose(); }
      else toast?.("Ошибка: " + (j.error || "?"));
    } catch (e) { setBusy(false); toast?.("Сеть: " + e); }
  };

  return (
    <Dialog open={!!project} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Настройки: {project}</DialogTitle>
      <DialogContent>
        <Typography variant="caption" color="text.secondary">
          Пустые значения наследуются из настроек аккаунта.
        </Typography>
        <Stack spacing={2} sx={{ mt: 1.5 }}>
          <TextField select label="Модель" size="small" fullWidth
                     value={model}
                     onChange={e => setModel(e.target.value)}
                     helperText="пусто — модель из настроек">
            <MenuItem value="">— по умолчанию —</MenuItem>
            {models.map(m => (
              <MenuItem key={m.id} value={m.id}>{m.id}</MenuItem>))}
          </TextField>
          <TextField select label="Режим ответа" size="small" fullWidth
                     value={mode}
                     onChange={e => setMode(e.target.value)}
                     helperText="пусто — режим из настроек">
            <MenuItem value="">— по умолчанию —</MenuItem>
            <MenuItem value="code">🛠 код</MenuItem>
            <MenuItem value="ask">💬 вопрос</MenuItem>
          </TextField>
          <FormControlLabel
            control={<Checkbox checked={autoCommit}
                     onChange={e => setAutoCommit(e.target.checked)} />}
            label="Автокоммит + push после задачи" />
          <TextField select label="Рабочая ветка" size="small" fullWidth
                     value={mainBranch}
                     onChange={e => setMainBranch(e.target.value)}
                     helperText="куда сливать ветки кнопкой в «Ветки» — пусто: main/master">
            <MenuItem value="">— по умолчанию —</MenuItem>
            {mainBranch && !branches.includes(mainBranch) &&
              <MenuItem value={mainBranch}>{mainBranch}</MenuItem>}
            {branches.map(b => (
              <MenuItem key={b} value={b}>{b}</MenuItem>))}
          </TextField>
          <TextField label="MCP серверы проекта" size="small" fullWidth
                     multiline minRows={2} maxRows={8}
                     value={mcp}
                     onChange={e => setMcp(e.target.value)}
                     helperText='JSON-объект name → def (как mcpServers); применяются только к задачам этого проекта'
                     InputProps={{ sx: { fontFamily: "monospace" } }}
                     placeholder='{"my-db": {"command": "mcp-server", "args": ["--db", "x"]}}' />
        </Stack>
      </DialogContent>
      <DialogActions>
        {project !== "devin-cli" && (
          <Button color="error" disabled={busy}
                  onClick={() => setAskDel(true)}
                  sx={{ mr: "auto", textTransform: "none" }}>
            Удалить</Button>)}
        <Button onClick={onClose}>Отмена</Button>
        <Button variant="contained" onClick={save} disabled={busy}>
          Сохранить</Button>
      </DialogActions>
      <Dialog open={askDel} onClose={() => setAskDel(false)}>
        <DialogTitle>Удалить «{project}»?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            Будет удалена папка проекта на сервере и его записи в базе
            (настройки, привязки инструкций, права). Репозиторий на
            GitHub не трогаем. Действие необратимо.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAskDel(false)}>Отмена</Button>
          <Button color="error" variant="contained" disabled={busy}
                  onClick={del}>
            Удалить</Button>
        </DialogActions>
      </Dialog>
    </Dialog>
  );
}
