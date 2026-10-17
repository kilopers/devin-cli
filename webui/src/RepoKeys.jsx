// Ключи репозиториев — список сохранённых git-токенов (GitHub/GitLab)
// из профиля; токены живут на сервере (kv.git_creds), здесь видны только
// последние 4 символа. «Добавить» — вторая модалка поверх: тип GitHub
// (нужен только ключ) или GitLab (домен + ключ, self-hosted поддержан).
import { useState } from "react";
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button,
  Stack, Typography, IconButton, TextField, List, ListItem,
  ListItemText, ListItemIcon, ListItemSecondaryAction, Alert,
  FormControl, InputLabel, Select, MenuItem,
} from "@mui/material";
import GitHubIcon from "@mui/icons-material/GitHub";
import DeleteIcon from "@mui/icons-material/Delete";
import AddIcon from "@mui/icons-material/Add";
import { apiJson as get, post } from "./api.js";

export default function RepoKeys({ open, onClose }) {
  const [creds, setCreds] = useState(null); // null = ещё не грузили
  const [add, setAdd] = useState(false);
  const [type, setType] = useState("github");
  const [host, setHost] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const load = () => get("/api/creds").then(j => setCreds(j.creds || []));
  if (open && creds === null) load();

  const save = async () => {
    setBusy(true); setMsg(null);
    const j = await post("/api/creds", {
      type, host: host.trim(), token: token.trim() });
    setBusy(false);
    if (!j.ok) return setMsg({ ok: false, text: j.error });
    setMsg({ ok: true, text: `ключ для ${j.host} сохранён` +
      (j.updated ? ` — обновлено ${j.updated} remote` : "") });
    setAdd(false); setToken(""); setHost(""); load();
  };

  const del = async (h) => {
    await post("/api/creds/delete", { host: h });
    load();
  };

  return (
    <>
      <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
        <DialogTitle>Ключи репозиториев</DialogTitle>
        <DialogContent>
          <Typography variant="caption" color="text.secondary">
            Токены для клона приватных репозиториев и CI. При добавлении
            проекта по https-ссылке ключ подставляется по домену хоста.
          </Typography>
          {msg && <Alert severity={msg.ok ? "success" : "error"}
                          sx={{ mt: 1 }}>{msg.text}</Alert>}
          <List dense>
            {(creds || []).map(c => (
              <ListItem key={c.host} disableGutters>
                <ListItemIcon><GitHubIcon /></ListItemIcon>
                <ListItemText primary={c.host}
                  secondary={(c.kind === "github" ? "GitHub" : "GitLab") +
                    " · " + c.mask} />
                <ListItemSecondaryAction>
                  <IconButton edge="end" onClick={() => del(c.host)}>
                    <DeleteIcon />
                  </IconButton>
                </ListItemSecondaryAction>
              </ListItem>
            ))}
            {creds && !creds.length &&
              <Typography color="text.secondary" sx={{ mt: 1 }}>
                ключей пока нет</Typography>}
          </List>
          <Button startIcon={<AddIcon />} onClick={() => setAdd(true)}
                  variant="outlined" size="small" sx={{ mt: 1 }}>
            Добавить ключ
          </Button>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Закрыть</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={add} onClose={() => setAdd(false)} fullWidth maxWidth="xs">
        <DialogTitle>Новый ключ</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 0.5 }}>
            <FormControl size="small">
              <InputLabel>Тип</InputLabel>
              <Select value={type} label="Тип"
                      onChange={e => setType(e.target.value)}>
                <MenuItem value="github">GitHub</MenuItem>
                <MenuItem value="gitlab">GitLab</MenuItem>
              </Select>
            </FormControl>
            {type === "gitlab" && (
              <TextField label="Домен" size="small" value={host}
                onChange={e => setHost(e.target.value)}
                placeholder="gitlab.com или git.example.com"
                helperText="self-hosted GitLab укажи своим доменом" />
            )}
            <TextField label="Токен" size="small" type="password"
              value={token} onChange={e => setToken(e.target.value)}
              helperText={type === "github"
                ? "ghp_… или github_pat_… (classic repo / fine-grained)"
                : "glpat-… (PAT) или gldt-… (deploy token)"} />
            <Typography variant="caption" color="text.secondary">
              Если ключ меняется — remote всех проектов этого хоста
              обновятся автоматически.
            </Typography>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAdd(false)}>Отмена</Button>
          <Button variant="contained" onClick={save}
                  disabled={busy || !token.trim() ||
                            (type === "gitlab" && !host.trim())}>
            Сохранить
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
