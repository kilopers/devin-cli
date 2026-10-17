// Управление пользователями — только для админа: список учёток веба,
// «Создать» — логин+пароль, «Удалить» — проекты юзера уходят админу.
import { useState } from "react";
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button,
  Stack, Typography, IconButton, TextField, List, ListItem,
  ListItemText, ListItemSecondaryAction, Alert,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import AddIcon from "@mui/icons-material/Add";
import AdminIcon from "@mui/icons-material/AdminPanelSettings";
import { apiJson as get, post } from "./api.js";

export default function Users({ open, onClose, me }) {
  const [users, setUsers] = useState(null);
  const [login, setLogin] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const load = () => get("/api/users").then(j => setUsers(j.users || []));
  if (open && users === null) load();

  const create = async () => {
    setBusy(true); setMsg(null);
    const j = await post("/api/users",
                         { user: login.trim(), password: pw });
    setBusy(false);
    if (!j.ok) return setMsg({ ok: false, text: j.error });
    setMsg({ ok: true, text: `пользователь ${j.user} создан` });
    setLogin(""); setPw(""); load();
  };

  const del = async (u) => {
    await post("/api/users/delete", { user: u });
    setMsg({ ok: true, text: `${u} удалён, проекты → админ` });
    load();
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Пользователи</DialogTitle>
      <DialogContent>
        <Typography variant="caption" color="text.secondary">
          У каждого — свои ключи и проекты; папка projects/ общая.
        </Typography>
        {msg && <Alert severity={msg.ok ? "success" : "error"}
                        sx={{ mt: 1 }}>{msg.text}</Alert>}
        <List dense>
          {(users || []).map(u => (
            <ListItem key={u.user} disableGutters>
              <ListItemText primary={u.user}
                secondary={u.admin ? "админ" : "пользователь"} />
              {!u.admin && u.user !== me &&
                <ListItemSecondaryAction>
                  <IconButton edge="end" onClick={() => del(u.user)}>
                    <DeleteIcon />
                  </IconButton>
                </ListItemSecondaryAction>}
            </ListItem>
          ))}
        </List>
        <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
          <TextField label="Логин" size="small" value={login}
                     onChange={e => setLogin(e.target.value)}
                     autoComplete="off" />
          <TextField label="Пароль" size="small" type="password" value={pw}
                     onChange={e => setPw(e.target.value)} />
          <Button variant="contained" startIcon={<AddIcon />}
                  onClick={create}
                  disabled={busy || !login.trim() || pw.length < 6}>
            Создать
          </Button>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Закрыть</Button>
      </DialogActions>
    </Dialog>
  );
}
