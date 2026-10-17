// Настройки юзера — API-ключи и параметры задач: devin, STT-цепочка,
// telegram, gitlab base, git identity. Секреты хранятся зашифрованными
// (enc:v1), в форме видна только маска; пустое поле = не менять.
import { useState } from "react";
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button,
  Stack, Typography, TextField, Alert, IconButton, Tooltip,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import { apiJson as get, post } from "./api.js";

export default function Settings({ open, onClose }) {
  const [fields, setFields] = useState(null);
  const [vals, setVals] = useState({});     // текущие маски
  const [edit, setEdit] = useState({});     // введённые новые значения
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const load = () => get("/api/settings").then(j => {
    setFields(j.fields || []); setVals(j.settings || {}); });
  if (open && fields === null) load();

  const save = async () => {
    setBusy(true); setMsg(null);
    const j = await post("/api/settings", edit);
    setBusy(false);
    if (!j.ok) return setMsg({ ok: false, text: j.error });
    setEdit({}); onClose();
  };

  const clear = async (k) => {
    await post("/api/settings", { clear: [k] });
    load();
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Настройки аккаунта</DialogTitle>
      <DialogContent>
        <Typography variant="caption" color="text.secondary">
          Ключи шифруются при хранении. Пустое поле — оставить как есть;
          🗑 — удалить значение (вернётся env-дефолт).
        </Typography>
        {msg && <Alert severity={msg.ok ? "success" : "error"}
                        sx={{ mt: 1 }}>{msg.text}</Alert>}
        <Stack spacing={1.5} sx={{ mt: 1.5 }}>
          {(fields || []).map(f => (
            <TextField key={f.key} size="small" fullWidth
              label={f.label}
              type={f.secret ? "password" : "text"}
              autoComplete="off"
              value={edit[f.key] ?? ""}
              onChange={e => setEdit({ ...edit, [f.key]: e.target.value })}
              placeholder={vals[f.key] ? String(vals[f.key])
                           : (f.env ? "env: " + f.env : "не задано")}
              helperText={f.hint +
                (!vals[f.key] && f.env ? " (берётся из env)" : "")}
              InputProps={vals[f.key] ? { endAdornment:
                <Tooltip title="удалить значение">
                  <IconButton size="small" onClick={() => clear(f.key)}>
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Tooltip> } : undefined} />
          ))}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Закрыть</Button>
        <Button variant="contained" onClick={save}
                disabled={busy || !Object.values(edit).some(v => v)}>
          Сохранить
        </Button>
      </DialogActions>
    </Dialog>
  );
}
