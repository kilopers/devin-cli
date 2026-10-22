// Настройки юзера — API-ключи и параметры задач: devin, STT-цепочка,
// telegram, gitlab base, git identity. Секреты хранятся зашифрованными
// (enc:v1), в форме видна только маска; пустое поле = не менять.
import { useEffect, useState } from "react";
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button,
  Stack, Typography, TextField, Alert, IconButton, Tooltip,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import { FormControlLabel, Checkbox, Divider } from "@mui/material";
import { apiJson as get, post } from "./api.js";

export default function Settings({ open, onClose, onChanged }) {
  const [fields, setFields] = useState(null);
  const [vals, setVals] = useState({});     // текущие маски
  const [edit, setEdit] = useState({});     // введённые новые значения
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [extKey, setExtKey] = useState(null); // null — ещё не грузили

  const load = () => {
    get("/api/settings").then(j => {
      setFields(j.fields || []); setVals(j.settings || {}); });
    get("/api/extkey").then(j =>
      setExtKey(j.set ? j.key : "")).catch(() => {});
  };
  // перечитываем при каждом открытии — иначе после сохранения
  // показывались старые значения
  useEffect(() => { if (open) load(); }, [open]);

  const save = async () => {
    setBusy(true); setMsg(null);
    const j = await post("/api/settings", edit);
    setBusy(false);
    if (!j.ok) return setMsg({ ok: false, text: j.error });
    if ("all_projects" in edit) onChanged?.();
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
        <Divider sx={{ mt: 1.5 }} />
        <FormControlLabel sx={{ display: "block", mt: 1 }}
          control={
            <Checkbox size="small"
              checked={(edit.all_projects ?? vals.all_projects) === "1"}
              onChange={e => setEdit({ ...edit,
                all_projects: e.target.checked ? "1" : "0" })} />}
          label="Показывать все проекты (из всех пространств)" />
        <Stack direction="row" spacing={1} alignItems="center">
          <Typography variant="body2" sx={{ flex: 1 }}>
            Ключ внешнего API: {extKey === null ? "…" :
              (extKey || "не создан")}
          </Typography>
          <Button size="small" variant="outlined"
            onClick={async () => {
              const j = await post("/api/extkey", { action: "gen" });
              setMsg({ ok: j.ok, text: j.ok
                ? "Новый ключ: " + j.key + " — сохрани, больше не покажется"
                : j.error });
              if (j.ok) setExtKey(j.key.slice(0,7) + "…" + j.key.slice(-4));
            }}>
            {extKey ? "Перевыпустить" : "Создать"}
          </Button>
          {!!extKey &&
            <Button size="small" color="error"
              onClick={async () => {
                await post("/api/extkey", { action: "revoke" });
                setExtKey(""); }}>
              Удалить</Button>}
        </Stack>
        <Stack spacing={1.5} sx={{ mt: 0.5 }}>
          {(fields || []).map(f => (
            <TextField key={f.key} size="small" fullWidth
              label={f.label}
              type="text"
              autoComplete="off"
              value={edit[f.key] ?? (vals[f.key] || f.env || "")}
              onChange={e => setEdit({ ...edit, [f.key]: e.target.value })}
              helperText={f.hint +
                (vals[f.key] ? "" : f.env ? " (из env)" : "")}
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
                disabled={busy || !(Object.values(edit).some(v => v)
                  || ("all_projects" in edit
                      && edit.all_projects !== (vals.all_projects || "")))}>
          Сохранить
        </Button>
      </DialogActions>
    </Dialog>
  );
}
