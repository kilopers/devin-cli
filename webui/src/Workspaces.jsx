// Рабочие пространства — список пространств юзера: активное (клик по
// строке), цветной кружок, переименование, удаление (кроме дефолтного),
// создание нового. Цвет активного пространства красит шапку и нижний бар.
import { useState } from "react";
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button,
  Stack, Typography, IconButton, TextField, List, ListItem,
  ListItemText, ListItemSecondaryAction, Alert, Radio, Box, Tooltip,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import CasinoIcon from "@mui/icons-material/Casino";
import EditIcon from "@mui/icons-material/Edit";
import AddIcon from "@mui/icons-material/Add";
import { apiJson as get, post } from "./api.js";

const COLORS = ["#1565c0", "#2e7d32", "#6a1b9a", "#ef6c00", "#c62828",
                "#00838f", "#455a64", "#ad1457"];

// случайный «фирменный» цвет: равномерный hue, приглушённые тона,
// чтобы шапка не выжигала глаза
const randColor = () => {
  const h = Math.floor(Math.random() * 360);
  const s = 55 + Math.floor(Math.random() * 20);   // 55-75%
  const l = 32 + Math.floor(Math.random() * 14);   // 32-46%
  const f = (n) => {
    const k = (n + h / 30) % 12;
    const a = s / 100 * Math.min(l / 100, 1 - l / 100);
    const v = l / 100 - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return Math.round(v * 255).toString(16).padStart(2, "0");
  };
  return `#${f(0)}${f(8)}${f(4)}`;
};

export const Dot = ({ color, size = 12 }) => (
  <Box component="span" sx={{
    display: "inline-block", width: size, height: size, borderRadius: "50%",
    bgcolor: color || "#999", mr: 0.8, verticalAlign: "middle",
    border: "1px solid rgba(0,0,0,.15)" }} />
);

export default function Workspaces({ open, onClose, onChanged }) {
  const [ws, setWs] = useState(null);
  const [active, setActive] = useState(0);
  const [name, setName] = useState("");
  const [color, setColor] = useState(COLORS[0]);
  const [edit, setEdit] = useState(null); // {id,name,color}
  const [msg, setMsg] = useState(null);

  const load = () => get("/api/ws").then(j => {
    setWs(j.ws || []); setActive(j.active || 0); });
  if (open && ws === null) load();

  const reload = () => { load(); onChanged?.(); };

  const pick = async id => {
    await post("/api/ws/active", { id }); reload();
  };
  const create = async () => {
    const j = await post("/api/ws", { name: name.trim(), color });
    if (!j.ok) return setMsg({ ok: false, text: j.error });
    setMsg(null); setName(""); reload();
  };
  const save = async () => {
    await post("/api/ws/update", { id: edit.id, name: edit.name,
                                   color: edit.color });
    setEdit(null); reload();
  };
  const del = async w => {
    const j = await post("/api/ws/delete", { id: w.id });
    if (!j.ok) setMsg({ ok: false, text: j.error });
    else { setMsg(null); reload(); }
  };

  return (<>
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Рабочие пространства</DialogTitle>
      <DialogContent>
        <Typography variant="caption" color="text.secondary">
          Активное пространство показывает только свои проекты и красит
          шапку/нижний бар в свой цвет.
        </Typography>
        {msg && <Alert severity={msg.ok ? "success" : "error"}
                        sx={{ mt: 1 }}>{msg.text}</Alert>}
        <List dense>
          {(ws || []).map(w => (
            <ListItem key={w.id} disableGutters button
                      onClick={() => pick(w.id)}>
              <Radio size="small" checked={w.id === active}
                     sx={{ p: 0.5 }} />
              <ListItemText
                primary={<><Dot color={w.color} />{w.name}</>}
                secondary={w.default ? "по умолчанию" : ""} />
              <ListItemSecondaryAction>
                <IconButton edge="end" size="small"
                  onClick={e => { e.stopPropagation();
                                  setEdit({ ...w }); }}>
                  <EditIcon fontSize="small" />
                </IconButton>
                {!w.default &&
                  <IconButton edge="end" size="small"
                    onClick={e => { e.stopPropagation(); del(w); }}>
                    <DeleteIcon fontSize="small" />
                  </IconButton>}
              </ListItemSecondaryAction>
            </ListItem>
          ))}
        </List>
        <Typography variant="subtitle2" sx={{ mt: 1 }}>
          Новое пространство
        </Typography>
        <Stack spacing={1.2} sx={{ mt: 0.5 }}>
          <TextField label="Название" size="small" fullWidth value={name}
                     onChange={e => setName(e.target.value)} />
          <Box sx={{ display: "flex", gap: 1, alignItems: "center" }}>
            {COLORS.map(c => (
              <Box key={c} onClick={() => setColor(c)}
                   sx={{ width: 24, height: 24, borderRadius: "50%",
                         bgcolor: c, cursor: "pointer", flexShrink: 0,
                         outline: color === c ? "2px solid #000" : "none" }} />
            ))}
            <Tooltip title="случайный цвет">
              <IconButton size="small" onClick={() => setColor(randColor())}
                          sx={{ ml: "auto" }}>
                <CasinoIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>
          <Button variant="contained" startIcon={<AddIcon />} fullWidth
                  onClick={create} disabled={!name.trim()}>
            Создать
          </Button>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Закрыть</Button>
      </DialogActions>
    </Dialog>

    <Dialog open={!!edit} onClose={() => setEdit(null)} maxWidth="xs"
            fullWidth>
      <DialogTitle>Пространство</DialogTitle>
      <DialogContent>
        <Stack spacing={1.5} sx={{ mt: 0.5 }}>
          <TextField label="Название" size="small" fullWidth
                     value={edit?.name || ""}
                     onChange={e => setEdit({ ...edit,
                                              name: e.target.value })} />
          <Box sx={{ display: "flex", gap: 1, alignItems: "center" }}>
            {COLORS.map(c => (
              <Box key={c} onClick={() => setEdit({ ...edit, color: c })}
                   sx={{ width: 24, height: 24, borderRadius: "50%",
                         bgcolor: c, cursor: "pointer", flexShrink: 0,
                         outline: edit?.color === c
                           ? "2px solid #000" : "none" }} />
            ))}
            <Tooltip title="случайный цвет">
              <IconButton size="small"
                onClick={() => setEdit({ ...edit, color: randColor() })}
                sx={{ ml: "auto" }}>
                <CasinoIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setEdit(null)}>Отмена</Button>
        <Button variant="contained" onClick={save}>Сохранить</Button>
      </DialogActions>
    </Dialog>
  </>);
}
