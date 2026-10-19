// «Инструкции» — первая секция панели: системная (только чтение),
// общая пользовательская (пустая у всех, не удаляется), custom —
// создаются агентом через /api/internal/instr, здесь правятся,
// подключаются галочкой к текущему проекту и удаляются.
import { useEffect, useRef, useState } from "react";
import {
  Box, Checkbox, Chip, Collapse, Dialog, DialogActions,
  DialogContent, DialogTitle, IconButton, ListItemButton,
  TextField, Typography, Button,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import MenuBookIcon from "@mui/icons-material/MenuBook";
import DeleteIcon from "@mui/icons-material/Delete";
import { apiJson, post } from "./api.js";

export default function Instr({ project, open, onToggle, toast }) {
  const [rows, setRows] = useState([]);
  const [view, setView] = useState(null);      // открытая в модалке
  const [draft, setDraft] = useState({ name: "", body: "" });
  const projRef = useRef(project);
  projRef.current = project;

  const load = async () => {
    try {
      const d = await apiJson("/api/instr?project=" +
        encodeURIComponent(projRef.current || ""));
      if (d.ok) setRows(d.instructions || []);
    } catch (e) {}
  };
  useEffect(() => { setRows([]); load(); }, [project]);

  const openDlg = r => {
    setDraft({ name: r.name, body: r.body });
    setView(r);
  };

  const save = async () => {
    const d = await post("/api/instr", {
      action: "update", id: view.id, project: projRef.current,
      name: draft.name, body: draft.body });
    toast?.(d.ok ? "Инструкция сохранена"
                : "Ошибка: " + (d.error || "?"));
    if (d.ok) { setView(null); load(); }
  };

  const del = async () => {
    const d = await post("/api/instr", {
      action: "delete", id: view.id, project: projRef.current });
    toast?.(d.ok ? "Инструкция удалена"
                : "Ошибка: " + (d.error || "?"));
    if (d.ok) { setView(null); load(); }
  };

  const attach = async (r, on) => {
    const d = await post("/api/instr", {
      action: on ? "attach" : "detach", id: r.id,
      project: projRef.current });
    if (d.ok) load();
    else toast?.("Ошибка: " + (d.error || "?"));
  };

  const system = rows.find(r => r.kind === "system");
  const common = rows.find(r => r.kind === "user");
  const customs = rows.filter(r => r.kind === "custom");
  const count = rows.filter(
    r => r.kind !== "custom" || r.attached).length;

  return (<>
    <ListItemButton dense onClick={onToggle} sx={{ px: 1.5, py: 0.5 }}>
      {open ? <ExpandLessIcon sx={{ fontSize: 18 }} />
            : <ExpandMoreIcon sx={{ fontSize: 18 }} />}
      <MenuBookIcon sx={{ fontSize: 16, ml: 0.5 }} />
      <Typography variant="body2" sx={{ fontWeight: 500, ml: 0.5 }}>
        Инструкции
      </Typography>
      <Chip size="small" label={count}
            sx={{ ml: 1, height: 18, fontSize: 11 }} />
    </ListItemButton>
    <Collapse in={open}>
      <Box>
        {system && (
          <ListItemButton dense onClick={() => openDlg(system)}
                          sx={{ px: 1.5, py: 0.3 }}>
            <Checkbox size="small" checked disabled
                      sx={{ p: 0.3, mr: 0.5 }} />
            <Typography variant="body2" noWrap sx={{
              flex: 1, fontSize: 12.5, fontStyle: "italic",
              color: "text.secondary" }}>
              {system.name}
            </Typography>
            <Chip size="small" label="системная" color="primary"
                  variant="outlined"
                  sx={{ height: 16, fontSize: 10 }} />
          </ListItemButton>)}
        {common && (
          <ListItemButton dense onClick={() => openDlg(common)}
                          sx={{ px: 1.5, py: 0.3 }}>
            <Checkbox size="small" checked disabled
                      sx={{ p: 0.3, mr: 0.5 }}
                      title="подключается ко всем проектам" />
            <Typography variant="body2" noWrap sx={{
              flex: 1, fontSize: 12.5 }}>
              {common.name}
            </Typography>
            <Chip size="small" label="общая" variant="outlined"
                  sx={{ height: 16, fontSize: 10 }} />
          </ListItemButton>)}
        {customs.map(r => (
          <ListItemButton key={r.id} dense onClick={() => openDlg(r)}
                          sx={{ px: 1.5, py: 0.3 }}>
            <Checkbox size="small" checked={!!r.attached}
                      sx={{ p: 0.3, mr: 0.5 }}
                      title="подключена к проекту"
                      onClick={e => e.stopPropagation()}
                      onChange={e => attach(r, e.target.checked)} />
            <Typography variant="body2" noWrap sx={{
              flex: 1, fontSize: 12.5 }}>
              {r.name}
            </Typography>
          </ListItemButton>))}
      </Box>
    </Collapse>

    <Dialog open={!!view} onClose={() => setView(null)}
            fullWidth maxWidth="sm">
      <DialogTitle sx={{ fontSize: 16 }}>
        {view?.kind === "system" ? "Системная инструкция"
          : view?.kind === "user" ? "Общая инструкция"
          : "Инструкция"}
      </DialogTitle>
      <DialogContent>
        {view?.kind === "system" ? (
          <Typography variant="body2" component="pre" sx={{
            whiteSpace: "pre-wrap", fontSize: 12.5,
            fontFamily: "ui-monospace, Menlo, monospace",
            bgcolor: "#f5f5f5", p: 1.5, borderRadius: 1 }}>
            {draft.body || "—"}
          </Typography>
        ) : (<>
          {view?.kind === "custom" &&
            <TextField fullWidth size="small" label="Название"
                       value={draft.name}
                       onChange={e => setDraft(d =>
                         ({ ...d, name: e.target.value }))}
                       sx={{ mb: 1.5 }} />}
          <TextField fullWidth multiline minRows={8} size="small"
                     label="Текст (markdown)"
                     value={draft.body}
                     onChange={e => setDraft(d =>
                       ({ ...d, body: e.target.value }))} />
          {view?.kind === "user" &&
            <Typography variant="caption" color="text.secondary">
              Подключается к каждой твоей задаче во всех проектах.
            </Typography>}
        </>)}
      </DialogContent>
      <DialogActions>
        {view?.kind === "custom" &&
          <IconButton onClick={del} title="удалить" sx={{ mr: "auto" }}>
            <DeleteIcon fontSize="small" />
          </IconButton>}
        <Button onClick={() => setView(null)}>Закрыть</Button>
        {view && view.kind !== "system" &&
          <Button variant="contained" onClick={save}>Сохранить</Button>}
      </DialogActions>
    </Dialog>
  </>);
}
