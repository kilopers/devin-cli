// AddProject — «+ Добавить проект» in the project picker/drawer opens
// this dialog: folder name + repo URL (https or git@) + token, then
// POST /api/project/add clones it and the clone output shows in the
// dark <pre> right inside the modal.
import { useState } from "react";
import {
  Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle,
  TextField, Typography,
} from "@mui/material";
import { post } from "./api.js";

export default function AddProject({ open, onClose, onAdded }) {
  const [folder, setFolder] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);   // {ok, output|error}

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
    onClose();
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : close}
            maxWidth="sm" fullWidth>
      <DialogTitle sx={{ fontSize: 16 }}>Добавить проект</DialogTitle>
      <DialogContent sx={{ display: "flex", flexDirection: "column",
                           gap: 2, pt: "8px !important" }}>
        <TextField label="Папка проекта" size="small" value={folder}
                   onChange={e => setFolder(e.target.value)}
                   placeholder="my-repo"
                   helperText="Имя папки внутри projects/ — a-z, 0-9, точка, _ -" />
        <TextField label="Ссылка на репозиторий" size="small" value={url}
                   onChange={e => setUrl(e.target.value)}
                   placeholder="https://github.com/org/repo.git или git@gitlab.com:org/repo.git" />
        <TextField label="Токен" size="small" type="password" value={token}
                   onChange={e => setToken(e.target.value)}
                   helperText="GitHub: ghp_… или github_pat_… (repo) · GitLab: glpat-… (read+write repository). Вставляется в https-ссылку при клоне." />
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
                disabled={busy || !folder.trim() || !url.trim() ||
                          !token.trim()}>
          Клонировать
        </Button>
      </DialogActions>
    </Dialog>
  );
}
