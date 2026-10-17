// FileEditor — click a file in the project tree → fullscreen dialog with a
// CodeMirror 6 editor (syntax language picked from the file name via
// @codemirror/language-data, lazy-loaded). «Сохранить» / Ctrl+S → POST
// /api/file, which writes atomically server-side.
import { useEffect, useRef, useState } from "react";
import {
  Alert, AppBar, Box, Button, Dialog, IconButton, Toolbar, Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import SaveIcon from "@mui/icons-material/Save";
import { EditorView, basicSetup } from "codemirror";
import { Compartment } from "@codemirror/state";
import { keymap } from "@codemirror/view";
import { LanguageDescription } from "@codemirror/language";
import { languages } from "@codemirror/language-data";
import { oneDark } from "@codemirror/theme-one-dark";
import { apiJson, post } from "./api.js";

function CodeEditor({ filename, value, viewRef, onDirty, onSave }) {
  const hostRef = useRef(null);
  const cbRef = useRef({ onDirty, onSave });
  cbRef.current = { onDirty, onSave };

  useEffect(() => {
    const langConf = new Compartment();
    const view = new EditorView({
      parent: hostRef.current,
      doc: value,
      extensions: [
        basicSetup,
        oneDark,
        langConf.of([]),
        keymap.of([{ key: "Mod-s", preventDefault: true,
                     run: () => { cbRef.current.onSave?.(); return true; } }]),
        EditorView.updateListener.of(u => {
          if (u.docChanged) cbRef.current.onDirty?.();
        }),
        EditorView.theme({ "&": { height: "100%" },
                           ".cm-scroller": { overflow: "auto" } }),
      ],
    });
    viewRef.current = view;
    const desc = LanguageDescription.matchFilename(languages, filename);
    if (desc) {
      desc.load()
        .then(support => {
          if (view.dom.isConnected)
            view.dispatch({ effects: langConf.reconfigure(support) });
        })
        .catch(() => {});          // unknown dialect — plain text is fine
    }
    return () => { view.destroy(); viewRef.current = null; };
  }, []);                          // mounted once per dialog open
  return <Box ref={hostRef} sx={{ flex: 1, minHeight: 0, fontSize: 13,
                                  "& .cm-editor": { height: "100%" } }} />;
}

export default function FileEditor({ project, path, onClose, toast }) {
  // content: null → loading, {error} → failed, string → editable
  const [content, setContent] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const viewRef = useRef(null);

  useEffect(() => {
    if (path === null) return;
    setContent(null); setDirty(false);
    apiJson("/api/file?project=" + encodeURIComponent(project || "") +
            "&path=" + encodeURIComponent(path))
      .then(d => setContent(d.ok ? d.content
                                 : { error: d.error || "ошибка загрузки" }))
      .catch(e => setContent({ error: String(e) }));
  }, [path, project]);

  const save = async () => {
    const view = viewRef.current;
    if (!view || saving) return;
    setSaving(true);
    try {
      const d = await post("/api/file", {
        project: project || "", path,
        content: view.state.doc.toString(),
      });
      if (d.ok) { setDirty(false); toast?.("Сохранено: " + path); }
      else toast?.("Не сохранено: " + (d.error || "?"));
    } catch (e) {
      toast?.("Не сохранено: " + (e.message || e));
    }
    setSaving(false);
  };

  return (
    <Dialog fullScreen open={path !== null} onClose={onClose}>
      <AppBar position="sticky" color="primary">
        <Toolbar variant="dense" sx={{ gap: 1 }}>
          <IconButton color="inherit" onClick={onClose}>
            <CloseIcon />
          </IconButton>
          <Typography variant="body2" noWrap sx={{
            flex: 1, fontSize: 13,
            fontFamily: "ui-monospace, Menlo, monospace" }}>
            {path}{dirty ? " •" : ""}
          </Typography>
          <Button color="inherit" size="small" disabled={saving || !dirty}
                  startIcon={<SaveIcon />} onClick={save}>
            {saving ? "сохраняю…" : "Сохранить"}
          </Button>
        </Toolbar>
      </AppBar>
      <Box sx={{ display: "flex", flexDirection: "column", flex: 1,
                 minHeight: 0, bgcolor: "#282c34" }}>
        {path === null || content === null ? (
          <Typography sx={{ p: 2 }} color="text.secondary">
            загрузка…</Typography>
        ) : content.error ? (
          <Alert severity="warning" sx={{ m: 2 }}>{content.error}</Alert>
        ) : (
          <CodeEditor filename={path} value={content} viewRef={viewRef}
                      onDirty={() => setDirty(true)} onSave={save} />
        )}
      </Box>
    </Dialog>
  );
}
