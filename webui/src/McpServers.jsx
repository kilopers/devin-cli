// MCP серверы — управление mcpServers в ~/.config/devin/mcp_config.json
// (user scope, действует на все проекты воркера). stdio (command+args+env)
// или http (url+transport+headers). Подключённые серверы дают Devin CLI
// дополнительные инструменты — напр. mysql, github и т.п.
import { useState } from "react";
import {
  Alert, Box, Button, Checkbox, Chip, Dialog, DialogActions,
  DialogContent, DialogTitle, FormControl, FormControlLabel, IconButton,
  InputLabel, List, ListItem, ListItemSecondaryAction, ListItemText,
  MenuItem, Select, Stack, TextField, Typography,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import AddIcon from "@mui/icons-material/Add";
import { apiJson as get, post } from "./api.js";

const kvLines = d =>
  Object.entries(d || {}).map(([k, v]) => `${k}=${v}`).join("\n");

const emptyForm = { name: "", kind: "stdio", command: "", args: "",
                    env: "", url: "", transport: "http", headers: "",
                    disabled: false };

export default function McpServers({ open, onClose }) {
  const [servers, setServers] = useState(null); // null = ещё не грузили
  const [edit, setEdit] = useState(null);       // форма редактора или null
  const [isNew, setIsNew] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const load = () => get("/api/mcp/servers").then(j =>
    setServers(j.servers || []));
  if (open && servers === null) load();

  const openAdd = () => {
    setIsNew(true); setMsg(null);
    setEdit({ ...emptyForm });
  };
  const openEdit = s => {
    setIsNew(false); setMsg(null);
    setEdit({ name: s.name, kind: s.kind, command: s.command,
              args: s.args, env: kvLines(s.env), url: s.url,
              transport: s.transport || "http", headers: kvLines(s.headers),
              disabled: s.disabled });
  };

  const save = async () => {
    setBusy(true); setMsg(null);
    const j = await post("/api/mcp/servers", {
      action: "save", name: edit.name.trim(), server: {
        kind: edit.kind, command: edit.command, args: edit.args,
        env: edit.env, url: edit.url, transport: edit.transport,
        headers: edit.headers, disabled: edit.disabled,
      } });
    setBusy(false);
    if (!j.ok) return setMsg({ ok: false, text: j.error });
    setEdit(null); load();
  };

  const toggle = async s => {
    await post("/api/mcp/servers", { action: "toggle", name: s.name });
    load();
  };
  const del = async s => {
    await post("/api/mcp/servers", { action: "delete", name: s.name });
    load();
  };

  return (
    <>
      <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
        <DialogTitle>MCP серверы</DialogTitle>
        <DialogContent>
          <Typography variant="caption" color="text.secondary">
            Серверы из user-конфига Devin CLI — их инструменты доступны
            во всех задачах воркера. stdio — команда (npx, python…),
            http — удалённый сервер по URL.
          </Typography>
          {msg && <Alert severity={msg.ok ? "success" : "error"}
                          sx={{ mt: 1 }}>{msg.text}</Alert>}
          <List dense>
            {(servers || []).map(s => (
              <ListItem key={s.name} disableGutters>
                <ListItemText
                  primary={<Box sx={{ display: "flex", alignItems: "center",
                                      gap: 1 }}>
                    {s.name}
                    <Chip size="small" label={s.kind} variant="outlined"
                          sx={{ height: 18, fontSize: 10 }} />
                    {s.disabled &&
                      <Chip size="small" label="выкл" color="default"
                            sx={{ height: 18, fontSize: 10, opacity: .6 }} />}
                  </Box>}
                  secondary={s.kind === "http"
                    ? s.url
                    : `${s.command} ${s.args}`}
                  secondaryTypographyProps={{ noWrap: true,
                    sx: { fontFamily: "ui-monospace, Menlo, monospace",
                          fontSize: 11 } }} />
                <ListItemSecondaryAction>
                  <IconButton size="small" onClick={() => openEdit(s)}
                              title="править">
                    <EditIcon fontSize="small" /></IconButton>
                  <IconButton size="small" onClick={() => toggle(s)}
                              title={s.disabled ? "включить" : "выключить"}
                              sx={{ opacity: s.disabled ? .4 : 1 }}>
                    <Checkbox size="small" checked={!s.disabled}
                              disableRipple
                              sx={{ p: 0, pointerEvents: "none" }} />
                  </IconButton>
                  <IconButton edge="end" size="small"
                              onClick={() => del(s)} title="удалить">
                    <DeleteIcon fontSize="small" /></IconButton>
                </ListItemSecondaryAction>
              </ListItem>
            ))}
            {servers && !servers.length &&
              <Typography color="text.secondary" sx={{ mt: 1 }}>
                серверов пока нет</Typography>}
          </List>
          <Button startIcon={<AddIcon />} onClick={openAdd}
                  variant="outlined" size="small" sx={{ mt: 1 }}>
            Добавить сервер
          </Button>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Закрыть</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!edit} onClose={() => setEdit(null)}
              fullWidth maxWidth="xs">
        <DialogTitle>{isNew ? "Новый MCP сервер" : `MCP: ${edit?.name}`}
        </DialogTitle>
        {edit &&
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 0.5 }}>
            <TextField label="Имя" size="small" value={edit.name}
              disabled={!isNew}
              onChange={e => setEdit({ ...edit, name: e.target.value })}
              helperText="a-z, 0-9, _ и - — например mysql" />
            <FormControl size="small">
              <InputLabel>Тип</InputLabel>
              <Select value={edit.kind} label="Тип"
                onChange={e => setEdit({ ...edit, kind: e.target.value })}>
                <MenuItem value="stdio">stdio (локальная команда)</MenuItem>
                <MenuItem value="http">http (удалённый сервер)</MenuItem>
              </Select>
            </FormControl>
            {edit.kind === "stdio" ? (
              <>
                <TextField label="Команда" size="small" value={edit.command}
                  onChange={e => setEdit({ ...edit, command: e.target.value })}
                  placeholder="npx" />
                <TextField label="Аргументы" size="small" value={edit.args}
                  onChange={e => setEdit({ ...edit, args: e.target.value })}
                  placeholder="-y @benborla29/mcp-server-mysql"
                  helperText="строка — разобьётся по пробелам (кавычки ок)" />
                <TextField label="Переменные окружения" size="small"
                  multiline minRows={3} value={edit.env}
                  onChange={e => setEdit({ ...edit, env: e.target.value })}
                  placeholder={"MYSQL_HOST=db\nMYSQL_USER=moodle\n" +
                               "MYSQL_PASS=secret\nMYSQL_DB=moodle"}
                  helperText="по одной KEY=VALUE в строке" />
              </>
            ) : (
              <>
                <TextField label="URL" size="small" value={edit.url}
                  onChange={e => setEdit({ ...edit, url: e.target.value })}
                  placeholder="https://mcp.example.com/mcp" />
                <FormControl size="small">
                  <InputLabel>Транспорт</InputLabel>
                  <Select value={edit.transport} label="Транспорт"
                    onChange={e => setEdit({ ...edit,
                                             transport: e.target.value })}>
                    <MenuItem value="http">Streamable HTTP</MenuItem>
                    <MenuItem value="sse">SSE (legacy)</MenuItem>
                  </Select>
                </FormControl>
                <TextField label="Заголовки" size="small" multiline
                  minRows={2} value={edit.headers}
                  onChange={e => setEdit({ ...edit,
                                           headers: e.target.value })}
                  placeholder="Authorization=Bearer …"
                  helperText="по одной KEY=VALUE в строке" />
              </>
            )}
            <FormControlLabel
              control={<Checkbox checked={edit.disabled}
                onChange={e => setEdit({ ...edit,
                                         disabled: e.target.checked })} />}
              label="Отключён (конфиг есть, сервер не запускается)" />
          </Stack>
        </DialogContent>}
        <DialogActions>
          <Button onClick={() => setEdit(null)}>Отмена</Button>
          <Button variant="contained" onClick={save}
            disabled={busy || !edit?.name.trim() ||
              (edit?.kind === "http" ? !edit.url.trim()
                                     : !edit.command.trim())}>
            Сохранить
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
