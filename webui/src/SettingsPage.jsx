// Страница «Настройки» — отдельный экран (не модалка), как ModelsPage.
// Секции задаёт бэк: GET /api/settings отдаёт groups и поля с
// group/kind — новая настройка/группа добавляется строкой в
// SETTING_GROUPS/SETTING_FIELDS без правок фронта. Секреты шифруются
// при хранении (enc:v1); пустое поле = не менять, 🗑 = удалить.
// Доп. секции: ext-ключ, микрофон диктовки, ключи репозиториев.
import { useEffect, useState } from "react";
import {
  Alert, AppBar, Box, Button, Checkbox, FormControlLabel, IconButton,
  Paper, Radio, RadioGroup, Stack, TextField, Toolbar, Tooltip,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import DeleteIcon from "@mui/icons-material/Delete";
import SettingsIcon from "@mui/icons-material/Settings";
import KeyIcon from "@mui/icons-material/Key";
import MicIcon from "@mui/icons-material/Mic";
import { apiJson as get, post } from "./api.js";
import { micDeviceId, setMicDeviceId, listMics } from "./audio.js";
import RepoKeys from "./RepoKeys.jsx";

const MicSel = () => {
  const [micId, setMicId] = useState(micDeviceId());
  const [micList, setMicList] = useState([]);
  useEffect(() => { listMics().then(setMicList).catch(() => {}); }, []);
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">
        Микрофон для диктовки
      </Typography>
      {!micList.length &&
        <Typography variant="body2" color="text.secondary"
                    sx={{ fontSize: 12.5, py: 0.5 }}>
          Микрофоны не найдены — проверь, что браузеру разрешён доступ.
        </Typography>}
      <RadioGroup value={micId}
                  onChange={e => { setMicId(e.target.value);
                                   setMicDeviceId(e.target.value); }}>
        <FormControlLabel value="" control={<Radio size="small" />}
          label={<Typography sx={{ fontSize: 13 }}>
                   По умолчанию (системный)</Typography>} />
        {micList.map((d, i) =>
          <FormControlLabel key={d.deviceId || i}
            value={d.deviceId} control={<Radio size="small" />}
            label={<Typography sx={{ fontSize: 13 }}>
                     {d.label || "устройство " + (i + 1)}
                   </Typography>} />)}
      </RadioGroup>
    </Box>
  );
};

const ExtKey = ({ toast }) => {
  const [extKey, setExtKey] = useState(null); // null — ещё не грузили
  useEffect(() => {
    get("/api/extkey").then(j =>
      setExtKey(j.set ? j.key : "")).catch(() => {});
  }, []);
  return (
    <Box>
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography variant="body2" sx={{ flex: 1 }}>
          Ключ: {extKey === null ? "…" : (extKey || "не создан")}
        </Typography>
        <Button size="small" variant="outlined"
          onClick={async () => {
            const j = await post("/api/extkey", { action: "gen" });
            if (j.ok) {
              setExtKey(j.key.slice(0, 7) + "…" + j.key.slice(-4));
              toast?.("Новый ключ: " + j.key +
                      " — сохрани, больше не покажется");
            }
          }}>
          {extKey ? "Перевыпустить" : "Создать"}
        </Button>
        {!!extKey &&
          <Button size="small" color="error"
            onClick={async () => {
              await post("/api/extkey", { action: "revoke" });
              setExtKey("");
            }}>
            Удалить</Button>}
      </Stack>
    </Box>
  );
};

export default function SettingsPage({ accent, onClose, toast,
                                      onChanged }) {
  const [data, setData] = useState(null);    // ответ /api/settings
  const [vals, setVals] = useState({});      // текущие значения
  const [edit, setEdit] = useState({});      // введённые новые значения
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [keysOpen, setKeysOpen] = useState(false); // «Ключи репозиториев»

  const load = () => {
    get("/api/settings").then(j => {
      setData(j); setVals(j.settings || {});
    }).catch(e => setData({ error: String(e) }));
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    setBusy(true); setMsg(null);
    const j = await post("/api/settings", edit);
    setBusy(false);
    if (!j.ok) return setMsg({ ok: false, text: j.error });
    if ("all_projects" in edit) onChanged?.();
    setEdit({});
    toast?.("Сохранено");
    load();
  };

  const clear = async (k) => {
    await post("/api/settings", { clear: [k] });
    load();
  };

  const fields = data?.fields || [];
  const groups = (data?.groups || []).map(g => ({
    ...g, fields: fields.filter(f => (f.group || "") === g.key) }));
  // поля с группой вне реестра — в хвост, «Прочее»
  const rest = fields.filter(f =>
    !(data?.groups || []).some(g => g.key === f.group));
  if (rest.length)
    groups.push({ key: "_rest", label: "Прочее", hint: "", fields: rest });

  const dirty = Object.keys(edit).length > 0;

  return (
    <Box sx={{ width: "100%" }}>
      <AppBar position="sticky" color="primary"
              sx={{ bgcolor: accent, top: 0, zIndex: 5 }}>
        <Toolbar variant="dense">
          <SettingsIcon sx={{ mr: 1 }} />
          <Typography variant="h6" sx={{ fontSize: 16 }}>
            Настройки
          </Typography>
          <Box sx={{ flex: 1 }} />
          <Button size="small" variant="contained" onClick={save}
                  disabled={busy || !dirty}
                  sx={{ bgcolor: "rgba(255,255,255,.92)",
                        color: "#1c2128", mr: 1,
                        "&:hover": { bgcolor: "#fff" },
                        "&.Mui-disabled": {
                          bgcolor: "rgba(255,255,255,.35)",
                          color: "rgba(28,33,40,.5)" } }}>
            Сохранить
          </Button>
          <Tooltip title="закрыть">
            <IconButton color="inherit" onClick={onClose}>
              <CloseIcon />
            </IconButton>
          </Tooltip>
        </Toolbar>
      </AppBar>
      <Box sx={{ p: 1.5, pb: "150px", maxWidth: 900, mx: "auto",
                 width: "100%" }}>
        <Typography variant="caption" color="text.secondary">
          Ключи шифруются при хранении. Пустое поле — оставить как есть;
          🗑 — удалить значение (вернётся env-дефолт).
        </Typography>
        {msg && <Alert severity={msg.ok ? "success" : "error"}
                        sx={{ mt: 1 }}>{msg.text}</Alert>}
        {!data &&
          <Typography color="text.secondary" sx={{ mt: 2 }}>
            Загружаю настройки…</Typography>}
        {data?.error &&
          <Typography color="error" sx={{ mt: 2 }}>{data.error}</Typography>}

        {groups.map(g => (g.fields.length ||
                          g.key === "ext" || g.key === "ui" ||
                          g.key === "repos") && (
          <Paper key={g.key} variant="outlined"
                 sx={{ mt: 1.5, p: 1.5, borderRadius: "12px" }}>
            <Typography sx={{ fontSize: 14, fontWeight: 600 }}>
              {g.label}
              {!!g.fields.filter(f => f.set).length &&
                <Typography component="span" variant="caption"
                            color="text.secondary" sx={{ ml: 1 }}>
                  задано: {g.fields.filter(f => f.set).length}/
                    {g.fields.length}
                </Typography>}
            </Typography>
            {!!g.hint &&
              <Typography variant="caption" color="text.secondary">
                {g.hint}</Typography>}
            <Stack spacing={1.5} sx={{ mt: 1 }}>
              {g.fields.map(f => f.kind === "bool" ? (
                <FormControlLabel key={f.key}
                  control={
                    <Checkbox size="small"
                      checked={(edit[f.key] ?? vals[f.key] ?? "") === "1"}
                      onChange={e => setEdit({ ...edit,
                        [f.key]: e.target.checked ? "1" : "0" })} />}
                  label={
                    <Typography sx={{ fontSize: 13 }}>
                      {f.label}
                      {!!f.hint &&
                        <Typography component="span" variant="caption"
                                    color="text.secondary" sx={{ ml: 1 }}>
                          {f.hint}</Typography>}
                    </Typography>} />
              ) : (
                <TextField key={f.key} size="small" fullWidth
                  label={f.label}
                  autoComplete="off"
                  value={edit[f.key] ?? (vals[f.key] || f.env || "")}
                  onChange={e => setEdit({ ...edit,
                    [f.key]: e.target.value })}
                  helperText={f.hint +
                    (vals[f.key] ? "" : f.env ? " (из env)" : "")}
                  InputProps={vals[f.key] ? { endAdornment:
                    <Tooltip title="удалить значение">
                      <IconButton size="small"
                                  onClick={() => clear(f.key)}>
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip> } : undefined} />
              ))}
              {g.key === "ext" && <ExtKey toast={toast} />}
              {g.key === "ui" && <MicSel />}
              {g.key === "repos" &&
                <Box>
                  <Button size="small" variant="outlined"
                          startIcon={<KeyIcon />}
                          onClick={() => setKeysOpen(true)}>
                    Ключи репозиториев
                  </Button>
                </Box>}
            </Stack>
          </Paper>
        ))}
      </Box>
      <RepoKeys open={keysOpen} onClose={() => setKeysOpen(false)} />
    </Box>
  );
}
