// AddProject — «+ Добавить проект» in the project picker/drawer opens
// this dialog: folder name + repo URL (https or git@) + token, then
// POST /api/project/add clones it and the clone output shows in the
// dark <pre> right inside the modal.
import { useRef, useState } from "react";
import {
  Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle,
  TextField, Typography,
} from "@mui/material";
import { post } from "./api.js";

// provider guess + effective clone URL — mirrors backend logic:
// host "github.com" → GitHub (x-access-token), anything else → GitLab
// (oauth2). ssh git@ remotes clone via the ssh key — token unused.
function detect(url) {
  const m = url.trim().match(
    /^(?:https?|ssh):\/\/(?:[^@/\s]+@)?([^/:]+)(?::\d+)?\/(.+?)(?:\.git)?\/?$/) ||
    url.trim().match(/^[^@\s]+@([^:\s]+):(.+?)(?:\.git)?\/?$/);
  if (!m) return { kind: "unknown" };
  const [, host, path] = m;
  const ssh = url.trim().startsWith("git@") ||
              url.trim().startsWith("ssh://");
  if (ssh) return { kind: "ssh", host, path };
  const gh = host.toLowerCase() === "github.com";
  return { kind: gh ? "github" : "gitlab", host, path };
}

function previewUrl(url, token) {
  const d = detect(url);
  if (d.kind === "ssh") return url.trim() + "  (ssh-ключ, токен не нужен)";
  if (d.kind === "unknown") return "";
  const user = d.kind === "github" ? "x-access-token" : "oauth2";
  return `https://${user}:${token ? "***" : "<token>"}@${d.host}/` +
         `${d.path}.git`;
}

export default function AddProject({ open, onClose, onAdded }) {
  const [folder, setFolder] = useState("");
  const folderDirty = useRef(false);        // autofill until user edits
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);   // {ok, output|error}

  const kind = detect(url);
  const sshNote = kind.kind === "ssh";
  const tokenHint = "пусто — возьмём ключ из профиля → «Ключи " +
    "репозиториев» (" + (kind.kind === "gitlab"
      ? "glpat-…/gldt-…" : "ghp_…/github_pat_…") + ")";

  const urlChanged = v => {
    setUrl(v);
    if (!folderDirty.current) {
      const d = detect(v);
      if (d.path) setFolder(d.path.split("/").pop());
    }
  };

  const submit = async () => {
    setBusy(true); setResult(null);
    try {
      const d = await post("/api/project/add",
                           { folder, url, token });
      setResult(d.ok ? { ok: true, output: d.output || "готово" }
                     : { ok: false, output: d.error || "?" });
      if (d.ok) onAdded?.(d.folder);
    } catch (e) {
      setResult({ ok: false, output: String(e) });
    }
    setBusy(false);
  };

  const close = () => {
    setResult(null); setFolder(""); setUrl(""); setToken("");
    folderDirty.current = false;
    onClose();
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : close}
            maxWidth="sm" fullWidth>
      <DialogTitle sx={{ fontSize: 16 }}>
        Добавить проект
        {kind.kind !== "unknown" && (
          <Typography component="span" variant="caption"
                      sx={{ ml: 1, color: "text.secondary" }}>
            ({kind.kind === "ssh" ? "SSH" :
              kind.kind === "github" ? "GitHub" : "GitLab"})
          </Typography>
        )}
      </DialogTitle>
      <DialogContent sx={{ display: "flex", flexDirection: "column",
                           gap: 2, pt: "8px !important" }}>
        <TextField label="Ссылка на репозиторий" size="small" value={url}
                   onChange={e => urlChanged(e.target.value)}
                   placeholder="https://github.com/org/repo.git или git@gitlab.com:org/repo.git" />
        <TextField label="Папка проекта" size="small" value={folder}
                   onChange={e => { folderDirty.current = true;
                                    setFolder(e.target.value); }}
                   placeholder="my-repo"
                   helperText="Имя папки внутри projects/ — a-z, 0-9, точка, _ -" />
        {!sshNote && (
          <TextField label="Токен (необязательно)" size="small" type="password"
                     value={token}
                     onChange={e => setToken(e.target.value)}
                     helperText={tokenHint} />
        )}
        {url.trim() && kind.kind !== "unknown" && (
          <Typography variant="caption" sx={{
            fontFamily: "ui-monospace, Menlo, monospace", fontSize: 11,
            color: "text.secondary", wordBreak: "break-all" }}>
            {previewUrl(url, token)}
          </Typography>
        )}
        {busy && (
          <Typography variant="caption" color="text.secondary">
            клонирую…
          </Typography>
        )}
        {result && (
          <Box component="pre" sx={{
            m: 0, p: 1.5, borderRadius: 1, bgcolor: "#101418",
            color: result.ok ? "#7ee787" : "#ff7b72",
            fontSize: 11.5, lineHeight: 1.4, maxHeight: 180,
            overflow: "auto", whiteSpace: "pre-wrap",
            wordBreak: "break-all",
            fontFamily: "ui-monospace, Menlo, monospace" }}>
            {result.output}
          </Box>
        )}
        {result?.ok && (
          <Alert severity="success" sx={{ py: 0 }}>
            Проект склонирован и добавлен
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={close} disabled={busy}>Закрыть</Button>
        <Button variant="contained" onClick={submit}
                disabled={busy || !folder.trim() || !url.trim()}>
          Клонировать
        </Button>
      </DialogActions>
    </Dialog>
  );
}
