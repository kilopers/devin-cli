// Выбор движка («агента») в шапке: чип с текущим дефолтом, меню
// агентов реестра AGENTS. У ненастроенного — пункт «авторизация»:
// диалог со ссылкой на консоль провайдера и полем для ключа, ключ
// сохраняется в настройки юзера (cred_field из /api/agents).
// Выбор пишется в us:<u>.agent — движок по умолчанию для задач,
// у которых колонка/проект своего не задали.
import { useState } from "react";
import {
  Box, Button, Chip, Dialog, DialogActions, DialogContent,
  DialogTitle, IconButton, Menu, MenuItem, TextField, Tooltip,
  Typography,
} from "@mui/material";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import SettingsIcon from "@mui/icons-material/Settings";
import RadioButtonCheckedIcon from "@mui/icons-material/RadioButtonChecked";
import RadioButtonUncheckedIcon
  from "@mui/icons-material/RadioButtonUnchecked";
import { post } from "./api.js";

export default function AgentSel({ agents, onChanged, toast }) {
  const [anchor, setAnchor] = useState(null);
  const [auth, setAuth] = useState(null);   // агент диалога авторизации
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);

  if (!agents) return null;
  const list = agents.agents || [];
  const cur = list.find(a => a.key === agents.default);
  const icon = a => a.key === "claude" ? "🟣" : "🔷";

  const pick = async a => {
    setAnchor(null);
    if (!a.configured) { setAuth(a); return; }
    const j = await post("/api/agents", { agent: a.key });
    if (j.ok) { toast?.("Движок по умолчанию: " + a.label); onChanged?.(); }
    else toast?.("Ошибка: " + (j.error || "?"));
  };

  const saveKey = async () => {
    setBusy(true);
    const j = await post("/api/settings", { [auth.cred_field]: key.trim() });
    setBusy(false);
    if (j.ok) {
      toast?.(auth.label + " авторизован");
      await post("/api/agents", { agent: auth.key });  // новый — сразу дефолт
      setAuth(null); setKey(""); onChanged?.();
    } else toast?.("Ошибка: " + (j.error || "?"));
  };

  return (
    <>
      <Tooltip title="движок задач по умолчанию — выбор и авторизация агентов">
        <Chip size="small" clickable onClick={e => setAnchor(e.currentTarget)}
              icon={<SmartToyIcon sx={{ fontSize: 15, color: "inherit" }} />}
              label={(cur ? cur.label : "?") +
                    (agents.any ? "" : " — не настроен")}
              sx={{ color: "#fff", bgcolor: "rgba(255,255,255,.16)",
                    height: 24, fontSize: 11.5,
                    "& .MuiChip-icon": { color: "inherit" } }} />
      </Tooltip>
      <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}
            slotProps={{ paper: { sx: {
              borderRadius: "0 0 12px 12px", borderTop: "none",
              mt: "-2px" } } }}>
        {list.map(a => (
          <MenuItem key={a.key} onClick={() => pick(a)} dense
                    sx={{ pr: 0.5 }}>
            <Box sx={{ mr: 1, fontSize: 14 }}>{icon(a)}</Box>
            <Box sx={{ flex: 1, minWidth: 110 }}>
              <Typography sx={{ fontSize: 13 }}>{a.label}</Typography>
              {!a.configured &&
                <Typography variant="caption" color="warning.main">
                  не настроен — нужна авторизация
                </Typography>}
            </Box>
            {a.key === agents.default &&
              <RadioButtonCheckedIcon fontSize="small" color="primary" />}
            {a.key !== agents.default &&
              <RadioButtonUncheckedIcon fontSize="small"
                                        sx={{ color: "divider" }} />}
            <Tooltip title="авторизация">
              <IconButton size="small"
                onClick={e => { e.stopPropagation();
                                setAnchor(null); setAuth(a); }}>
                <SettingsIcon sx={{ fontSize: 16 }} />
              </IconButton>
            </Tooltip>
          </MenuItem>))}
      </Menu>
      <Dialog open={!!auth} onClose={() => setAuth(null)}
              fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontSize: 16 }}>
          Авторизация: {auth?.label}
        </DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Откройте страницу ключей, создайте ключ и вставьте его ниже —
            он сохранится в настройках аккаунта (зашифровано).
          </Typography>
          {!!auth?.auth_url &&
            <Button size="small" variant="outlined" component="a"
                    href={auth.auth_url} target="_blank" rel="noreferrer"
                    sx={{ mb: 2, textTransform: "none" }}>
              🔗 {auth.auth_url.replace(/^https?:\/\//, "")}
            </Button>}
          <TextField size="small" fullWidth autoFocus
                     label={auth?.label + " API ключ"}
                     placeholder="sk-…"
                     value={key}
                     onChange={e => setKey(e.target.value)}
                     onKeyDown={e => e.key === "Enter" && key.trim() && saveKey()} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAuth(null)}>Отмена</Button>
          <Button variant="contained" onClick={saveKey}
                  disabled={busy || !key.trim()}>
            Сохранить</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
