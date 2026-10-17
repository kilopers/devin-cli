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
import { apiJson as get, post } from "./api.js";

export default function Users({ open, onClose, me }) {
  const [users, setUsers] = useState(null);
  const [permFor, setPermFor] = useState(null); // юзер модалки прав
  const [allProj, setAllProj] = useState([]);
  const [granted, setGranted] = useState(new Set());
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

  const openPerms = async (u) => {
    const [pr, pe] = await Promise.all([
      get("/api/projects"), get("/api/users/perms?user=" + encodeURIComponent(u))]);
    setAllProj(pr.projects || []);
    setGranted(new Set(pe.granted || []));
    setPermFor(u); setMsg(null);
  };

  const savePerms = async () => {
    const j = await post("/api/users/perms",
                         { user: permFor, projects: [...granted] });
    if (j.ok) setMsg({ ok: true,
      text: `доступ ${permFor}: ${j.granted.join(", ") || "ничего"}` });
    setPermFor(null);
  };

  const del = async (u) => {
    await post("/api/users/delete", { user: u });
    setMsg({ ok: true, text: `${u} удалён, проекты → админ` });
    load();
  };

  const main = (
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
            <ListItem key={u.user} disableGutters button
                      onClick={() => !u.admin && openPerms(u.user)}>
              <ListItemText primary={u.user}
                secondary={(u.admin ? "админ" : "пользователь") +
                  (u.admin ? "" : " · клик — права на проекты")} />
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

  if (!permFor) return main;
  return (<>
    {main}
    <Dialog open onClose={() => setPermFor(null)} fullWidth maxWidth="xs">
      <DialogTitle>Права: {permFor}</DialogTitle>
      <DialogContent>
        <Typography variant="caption" color="text.secondary">
          Отмеченные проекты юзер увидит у себя и сможет в них работать.
          В git он ходит ключами владельца (токен зашит в remote).
        </Typography>
        <List dense>
          {allProj.map(p => (
            <ListItem key={p} disableGutters button
              onClick={() => setGranted(s => {
                const n = new Set(s); n.has(p) ? n.delete(p) : n.add(p);
                return n; })}>
              <ListItemText primary={p}
                secondary={granted.has(p) ? "доступ есть" : "нет доступа"} />
            </ListItem>
          ))}
          {!allProj.length &&
            <Typography color="text.secondary">проектов пока нет</Typography>}
        </List>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setPermFor(null)}>Отмена</Button>
        <Button variant="contained" onClick={savePerms}>Сохранить</Button>
      </DialogActions>
    </Dialog>
  </>);
}
