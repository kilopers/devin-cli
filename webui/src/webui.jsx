// Devin Worker web UI — React + MUI (was: Materialize + vanilla JS).
// Same JSON API as before; polling every 3 s, infinite scroll-up feed.
import React, { useCallback, useEffect, useLayoutEffect, useMemo,
                useRef, useState }
  from "react";
import { createRoot } from "react-dom/client";
import { createTheme, ThemeProvider } from "@mui/material/styles";
import {
  Alert, AppBar, Box, Button, Card, CardContent, Chip, CssBaseline,
  Dialog, DialogActions, DialogContent, DialogTitle, Divider,
  GlobalStyles, IconButton, List, ListItemButton, ListItemText,
  ListSubheader, MenuItem, Paper, Select, Snackbar, SwipeableDrawer,
  TextField, Toolbar, Tooltip, Typography,
} from "@mui/material";
import PersonIcon from "@mui/icons-material/Person";
import LogoutIcon from "@mui/icons-material/Logout";
import FolderOpenIcon from "@mui/icons-material/FolderOpen";
import RefreshIcon from "@mui/icons-material/Refresh";
import { api, apiJson, post } from "./api.js";
import Markdown from "./Markdown.jsx";
import FileTree from "./FileTree.jsx";
import Changes from "./Changes.jsx";
import FileEditor from "./FileEditor.jsx";
import AddProject from "./AddProject.jsx";
import Composer from "./Composer.jsx";
import { ConnBadge, useConnStatus } from "./ConnDot.jsx";

// Render crashes used to blank the whole page (white screen) — a
// boundary turns them into a readable error instead.
class ErrBoundary extends React.Component {
  constructor(p) { super(p); this.state = { err: null }; }
  static getDerivedStateFromError(err) { return { err }; }
  render() {
    return this.state.err
      ? <Box sx={{ p: 4 }}>
          <Typography color="error" variant="body2"
                      sx={{ fontFamily: "ui-monospace, monospace",
                            whiteSpace: "pre-wrap" }}>
            Ошибка интерфейса — обнови страницу (Ctrl+F5).{"\n"}
            {String(this.state.err)}
          </Typography>
        </Box>
      : this.props.children;
  }
}

const theme = createTheme({ palette: { primary: { main: "#3f51b5" } } });
const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";
const STATUS_RU = { queued: "в очереди", running: "выполняется", done: "готово" };
const SRC_RU = { telegram: "telegram", web: "web", file: "файл" };

const mdStyles = {
  body: { background: "#f5f7fb" },
  ".md": { fontSize: 14, lineHeight: 1.6, wordBreak: "break-word",
    maxHeight: 600, overflowY: "auto",
    "& > :first-child": { mt: 0 },
    "& h1,h2,h3,h4": { m: ".8em 0 .35em", fontWeight: 600, lineHeight: 1.3 },
    "& h1": { fontSize: "1.3em" }, "& h2": { fontSize: "1.2em" },
    "& h3": { fontSize: "1.1em" }, "& h4": { fontSize: "1em" },
    "& p": { m: ".45em 0" },
    "& pre": { bgcolor: "#101418", color: "#c9d1d9", borderRadius: "6px",
      p: "12px", overflowX: "auto", fontSize: "12.5px", lineHeight: 1.45,
      m: ".6em 0" },
    "& pre code": { background: "none", p: 0, color: "inherit", fontFamily: MONO },
    "& code": { fontFamily: MONO, fontSize: ".92em" },
    "& :not(pre) > code": { bgcolor: "#eceff1", color: "#ad1457",
      p: "1px 5px", borderRadius: "4px" },
    "& blockquote": { borderLeft: "3px solid #c5cae9", m: ".5em 0",
      p: "2px 12px", color: "#5f6368" },
    "& ul,& ol": { pl: "24px", m: ".4em 0" },
    "& a": { color: "#3f51b5" },
    "& table": { borderCollapse: "collapse", m: ".6em 0" },
    "& th,& td": { border: "1px solid #dadce0", p: "4px 10px", fontSize: 13 },
    "& th": { bgcolor: "#f1f3f4" },
    "& .hljs-addition, & .dline.add": { display: "block",
      bgcolor: "rgba(46,160,67,.4)", color: "#56d364", fontWeight: 500 },
    "& .hljs-deletion, & .dline.del": { display: "block",
      bgcolor: "rgba(248,81,73,.35)", color: "#ff7b72", fontWeight: 500 },
    "& .dline.meta, & .hljs-meta": { display: "block", color: "#79c0ff" },
    "& .dline.hunk": { display: "block", color: "#d2a8ff" },
    "& .hljs-comment": { color: "#8b949e" } },
  "pre.out": { background: "#101418", color: "#d3e3fd", borderRadius: "6px",
    padding: "12px", fontSize: "12.5px", lineHeight: 1.45,
    whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 480,
    overflowY: "auto", margin: 0, fontFamily: MONO },
};

function StatusChip({ t }) {
  const failed = t.status === "done" && t.task_status &&
    !/exit code: 0/.test(t.task_status);
  const color = failed || t.status === "running"
    ? (failed ? "error" : "info") : (t.status === "done" ? "success" : "default");
  return <Chip size="small" color={color} sx={{ height: 24, fontSize: 12 }}
    label={failed ? "ошибка" : (STATUS_RU[t.status] || t.status)}
    icon={t.status === "running"
      ? <Box component="span" sx={{ width: 10, height: 10, ml: "4px",
          border: "2px solid #90caf9", borderTopColor: "transparent",
          borderRadius: "50%", animation: "rot .8s linear infinite",
          "@keyframes rot": { to: { transform: "rotate(360deg)" } } }} />
      : undefined} />;
}

const TaskCard = React.memo(function TaskCard({ t, onCommit, onStop,
                                                onCancel }) {
  return (
    <Card sx={{ mb: 1.5 }}>
      <CardContent sx={{ p: "14px 18px", "&:last-child": { pb: "14px" } }}>
        <Box sx={{ display: "flex", justifyContent: "space-between",
                   alignItems: "center", gap: 1, flexWrap: "wrap" }}>
          <Typography variant="caption" color="text.secondary">
            {t.name} · {new Date(t.created * 1000).toLocaleString("ru-RU")}{" "}
            <Box component="span" sx={{ border: "1px solid #cfd8dc",
              borderRadius: "10px", px: "8px", py: "1px", fontSize: 11,
              color: "#78909c" }}>{SRC_RU[t.source] || t.source || ""}</Box>
            {t.model ? " " : null}
            {t.model &&
              <Box component="span" sx={{ border: "1px solid #cfd8dc",
                borderRadius: "10px", px: "8px", py: "1px", fontSize: 11,
                color: "#78909c" }}>{t.model}</Box>}
            {t.mode === "ask" ? " " : null}
            {t.mode === "ask" &&
              <Box component="span" sx={{ border: "1px solid #cfd8dc",
                borderRadius: "10px", px: "8px", py: "1px", fontSize: 11,
                color: "#78909c" }}>💬 вопрос</Box>}
          </Typography>
          <Box sx={{ display: "flex", alignItems: "center", gap: 0.8 }}>
            {t.status === "running" && onStop && (
              <Button size="small" variant="outlined" color="error"
                      onClick={() => onStop(t)}
                      sx={{ fontSize: 11, px: 1, py: 0, height: 24,
                            whiteSpace: "nowrap" }}>
                ⛔ стоп
              </Button>
            )}
            {t.status === "queued" && onCancel && (
              <Button size="small" variant="outlined" color="error"
                      onClick={() => onCancel(t)}
                      sx={{ fontSize: 11, px: 1, py: 0, height: 24,
                            whiteSpace: "nowrap" }}>
                ✖ удалить
              </Button>
            )}
            <StatusChip t={t} />
          </Box>
        </Box>
        <Typography variant="body2" sx={{ whiteSpace: "pre-wrap",
          fontWeight: 500, my: 1 }}>{t.prompt}</Typography>
        {t.output
          ? (t.status === "done"
              ? <Markdown text={t.output} />
              : <pre className="out">{t.output}</pre>)
          : null}
        {t.commit_offered ? (
          <Box sx={{ mt: 1.5, display: "flex", gap: 1 }}>
            <Button size="small" variant="contained" color="success"
                    onClick={() => onCommit(t.stem, "commit")}>
              ✅ закоммитить и запушить</Button>
            <Button size="small" onClick={() => onCommit(t.stem, "skip")}>
              ⏭ пропустить</Button>
          </Box>) : null}
      </CardContent>
    </Card>
  );
});

// Project picker in the header — replaces the old tabs row; selection
// persists server-side via POST /api/project (kv.project_web).
function ProjectSelect({ projects, current, onChange, onAdd }) {
  return (
    <Select size="small" value={current || ""} displayEmpty
            onChange={e => e.target.value === "__add__"
                      ? onAdd?.() : onChange(e.target.value)}
            sx={{ color: "#fff", height: 32, fontSize: 13, maxWidth: 200,
                  bgcolor: "rgba(255,255,255,.15)",
                  "& .MuiSelect-icon": { color: "rgba(255,255,255,.8)" } }}>
      {projects.map(p => <MenuItem key={p} value={p}>{p}</MenuItem>)}
      <MenuItem value="__add__" sx={{ color: "#1565c0", fontSize: 13 }}>
        ➕ Добавить проект…
      </MenuItem>
    </Select>
  );
}

function ModelSelect({ models, current, onChange, sx }) {
  return (
    <Select size="small" value={current || ""} onChange={e => onChange(e.target.value)}
            displayEmpty sx={{ color: "#fff", maxWidth: 320, height: 32,
              bgcolor: "rgba(255,255,255,.15)", fontSize: 13, ...sx }}>
      {(models.length ? models : [{ id: current, description: "" }]).map(m =>
        <MenuItem key={m.id} value={m.id}>
          {m.id + (m.description ? " — " + m.description.slice(0, 90) : "")}
        </MenuItem>)}
    </Select>
  );
}

function ModeSelect({ mode, onChange, sx }) {
  return (
    <Select size="small" value={mode} onChange={e => onChange(e.target.value)}
            sx={{ color: "#fff", height: 32,
              bgcolor: "rgba(255,255,255,.15)", fontSize: 13, ...sx }}>
      <MenuItem value="code">🛠 код</MenuItem>
      <MenuItem value="ask">💬 вопрос</MenuItem>
    </Select>
  );
}

export default function App() {
  const [projects, setProjects] = useState([]);
  const [multiMode, setMultiMode] = useState(false);
  const [project, setProject] = useState(null);
  const projRef = useRef(null);
  const [feed, setFeed] = useState(new Map());
  const [hasMore, setHasMore] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [status, setStatus] = useState({});
  const [models, setModels] = useState({ models: [], current: "" });
  const [mode, setMode] = useState("code");
  const [toast, setToast] = useState(null);
  const [toastNode, setToastNode] = useState(null);
  const [profileOpen, setProfileOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [pw, setPw] = useState({ cur: "", n1: "", n2: "" });
  const [treeVer, setTreeVer] = useState(0);
  const [editPath, setEditPath] = useState(null);   // file open in editor
  const [addOpen, setAddOpen] = useState(false);    // add-project dialog
  // shared confirm dialog: {kind:"stop"|"cancel", name, stem} | null
  const [confirm, setConfirm] = useState(null);
  // drawer keeps its scroll position across re-renders (selecting
  // mode/model inside it used to yank the list back to the top)
  const drawerBoxRef = useRef(null);
  const drawerScroll = useRef(0);
  useLayoutEffect(() => {
    const el = drawerBoxRef.current;
    if (el && el.scrollTop !== drawerScroll.current)
      el.scrollTop = drawerScroll.current;
  });
  // one SSE connection — shared by the desktop dot & the mobile bar
  const conn = useConnStatus(status.version);
  const modelFocus = useRef(false), modeFocus = useRef(false);
  const firstLoad = useRef(true);

  const items = useMemo(() =>
    [...feed.values()].sort((a, b) => a.created - b.created), [feed]);
  const oldestStem = items.length ? items[0].stem : null;

  const loadTasks = useCallback(async () => {
    const p = projRef.current;
    if (!p) return;
    try {
      const d = await apiJson("/api/tasks?project=" +
        encodeURIComponent(p) + "&limit=5");
      setFeed(m => {
        const n = new Map(m);
        // keep object identity for unchanged tasks (h = server-side
        // content hash) — React.memo(TaskCard) then skips re-render and
        // the feed stops flickering on identical polls
        d.tasks.forEach(t => {
          const prev = n.get(t.stem);
          if (!prev || prev.h !== t.h) n.set(t.stem, t);
        });
        return n;
      });
      if (firstLoad.current) { setHasMore(d.has_more); firstLoad.current = false; }
    } catch (e) {}
  }, []);

  const loadOlder = useCallback(async () => {
    const p = projRef.current;
    if (!hasMore || loadingOlder || !oldestStem || !p) return;
    setLoadingOlder(true);
    try {
      const prevH = document.body.scrollHeight, prevY = window.scrollY;
      const d = await apiJson("/api/tasks?project=" + encodeURIComponent(p) +
        "&limit=5&before=" + encodeURIComponent(oldestStem));
      setFeed(m => {
        const n = new Map(m);
        let got = false;
        d.tasks.forEach(t => {
          const prev = n.get(t.stem);
          if (!prev || prev.h !== t.h) { n.set(t.stem, t); got = true; }
        });
        setHasMore(got ? d.has_more : false);
        return n;
      });
      requestAnimationFrame(() =>
        window.scrollTo(0, prevY + document.body.scrollHeight - prevH));
    } catch (e) {}
    setLoadingOlder(false);
  }, [hasMore, loadingOlder, oldestStem]);

  const baseVer = useRef(null);   // version the page was loaded with
  const loadStatus = useCallback(async () => {
    try {
      const d = await apiJson("/api/status");
      // server got a newer build → hard-reload the whole page
      if (d.version) {
        if (baseVer.current === null) baseVer.current = d.version;
        else if (d.version !== baseVer.current) {
          location.reload(); return;
        }
      }
      setStatus(d);
      if (d.mode && !modeFocus.current) setMode(d.mode);
    } catch (e) {}
  }, []);

  const loadModels = useCallback(async () => {
    try {
      const d = await apiJson("/api/models");
      if (!modelFocus.current) setModels(d);
    } catch (e) {}
  }, []);

  const refreshProjects = async () => {
    try {
      const d = await apiJson("/api/projects");
      if (d.projects.length) { setProjects(d.projects); setMultiMode(true); }
    } catch (e) {}
  };

  const selectProject = useCallback(p => {
    setProject(p); projRef.current = p;
    if (multiMode)
      post("/api/project", { project: p })
        .then(d => { if (!d.ok) setToast("Проект: " + (d.error || "?")); })
        .catch(() => {});
    setFeed(new Map()); setHasMore(false); firstLoad.current = true;
    setDrawerOpen(false);
    loadTasks();
  }, [multiMode, loadTasks]);

  const commitAct = async (stem, action) => {
    try {
      const d = await post("/api/commit", { stem, action });
      if (d.ok && d.skipped) setToast("Пропущено — изменения остались в репо");
      else if (d.ok)
        setToastNode(
          <Box>Закоммичено и запушено
            {(d.result || "").trim() &&
              <pre className="out" style={{ maxWidth: "85vw" }}>
                {(d.result || "").trim().slice(-900)}</pre>}</Box>);
      else setToast("Коммит: " + (d.error || "?"));
    } catch (e) { setToast("Коммит сеть: " + e); }
    loadTasks();
  };

  // initial project list + tasks; polling every 3 s
  useEffect(() => {
    (async () => {
      try {
        const d = await apiJson("/api/projects");
        const projs = d.projects.length ? d.projects : ["workspace"];
        setProjects(projs); setMultiMode(!!d.projects.length);
        const cur = d.current || projs[0];
        setProject(cur); projRef.current = cur;
        loadTasks();
      } catch (e) {}
    })();
  }, [loadTasks]);

  useEffect(() => {
    loadStatus(); loadModels();
    const t = setInterval(() => { loadStatus(); loadTasks(); loadModels(); }, 3000);
    const onScroll = () => { if (window.scrollY < 200) loadOlder(); };
    window.addEventListener("scroll", onScroll);
    return () => { clearInterval(t); window.removeEventListener("scroll", onScroll); };
  }, [loadStatus, loadTasks, loadModels, loadOlder]);

  // stick to bottom when new output lands and we're already near it
  const sig = items.map(t => t.stem + t.status + (t.output || "").length).join();
  useEffect(() => {
    if (innerHeight + scrollY >= document.body.offsetHeight - 160)
      scrollTo(0, document.body.scrollHeight);
  }, [sig]);

  const statusText = (status.current_task ? "▶ " + status.current_task : "idle") +
    " · очередь " + (status.queue ?? "?") + " · " + (status.model || "");

  const setModel = m => post("/api/model", { model: m }).then(d => {
    setToast(d.ok ? "Модель: " + m : "Ошибка: " + (d.error || "?"));
    loadModels(); loadStatus();
  }).catch(() => {});

  const confirmAct = async () => {
    const c = confirm;
    setConfirm(null);
    try {
      const d = c.kind === "stop"
        ? await post("/api/stop", {})
        : await post("/api/task/cancel", { stem: c.stem });
      if (d.ok) {
        setToast(c.kind === "stop" ? "⛔ Остановлено: " + d.stopped
                                   : "Удалено из очереди: " + c.name);
        if (c.kind === "cancel")
          setFeed(m => { const n = new Map(m); n.delete(c.stem); return n; });
      } else setToast("Ошибка: " + (d.error || "?"));
      loadStatus();
    } catch (e) { setToast("Сеть: " + e); }
  };

  const setModeApi = m => post("/api/mode", { mode: m }).then(d => {
    setToast(d.ok ? (m === "ask" ? "Режим: ответ на вопрос" : "Режим: код")
                  : "Ошибка: " + (d.error || "?"));
    if (d.ok) setMode(m);
  }).catch(() => {});

  const savePw = async () => {
    if (pw.n1 !== pw.n2) return setToast("Новые пароли не совпадают");
    try {
      const d = await post("/api/password", { current: pw.cur, new: pw.n1 });
      setToast(d.ok ? "Пароль изменён" : "Ошибка: " + (d.error || "?"));
      if (d.ok) { setProfileOpen(false); setPw({ cur: "", n1: "", n2: "" }); }
    } catch (e) { setToast("Сеть: " + e); }
  };

  const logout = () => api("/logout", { method: "POST" })
    .finally(() => location = "/login");

  const drawer = (
    <Box ref={drawerBoxRef}
         onScroll={e => drawerScroll.current = e.currentTarget.scrollTop}
         sx={{ width: 300, height: "100%", overflowY: "auto" }}
         role="presentation">
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.2,
                 px: 2, py: 1.5, fontWeight: 600 }}>
        <img src="/static/favicon.svg" alt="" style={{ height: 22 }} />
        WebDev
      </Box>
      <List subheader={<ListSubheader>Проекты</ListSubheader>} dense>
        {projects.map(p => (
          <ListItemButton key={p} selected={p === project}
                          onClick={() => selectProject(p)}>
            <ListItemText primary={p} />
          </ListItemButton>))}
        <ListItemButton onClick={() => { setDrawerOpen(false);
                                         setAddOpen(true); }}>
          <ListItemText primary="➕ Добавить проект…"
                        primaryTypographyProps={{ color: "#1565c0",
                                                 fontSize: 14 }} />
        </ListItemButton>
      </List>
      <Divider />
      <ListSubheader>Файлы</ListSubheader>
      <Box sx={{ maxHeight: "40vh", overflow: "auto", px: 1 }}>
        <FileTree project={project} onError={setToast}
                  onOpenFile={setEditPath} />
      </Box>
      <Divider />
      <Changes project={project} toast={setToast} />
      <Divider />
      <Box sx={{ px: 2, py: 1.5, display: "flex", flexDirection: "column",
                 gap: 1.5 }}>
        <Typography variant="caption" color="text.secondary">
          {statusText}
        </Typography>
        <ModelSelect models={models.models} current={models.current}
                     onChange={setModel}
                     sx={{ color: "#212121", bgcolor: "#fff", maxWidth: "none",
                          border: "1px solid #dadce0" }} />
        <ModeSelect mode={mode} onChange={setModeApi}
                    sx={{ color: "#212121", bgcolor: "#fff",
                         border: "1px solid #dadce0" }} />
      </Box>
    </Box>
  );

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <GlobalStyles styles={mdStyles} />
      <ErrBoundary>
      <Box sx={{ display: "flex", flexDirection: "column", minHeight: "100vh" }}>
        <AppBar position="fixed" color="primary">
          <Toolbar variant="dense" sx={{ gap: 1 }}>
            <img src="/static/favicon.svg" alt=""
                 style={{ height: 24, filter: "invert(1)" }} />
            <Typography variant="h6" sx={{ fontSize: 19, flexShrink: 0,
                                           display: "flex",
                                           alignItems: "center", gap: 0.8 }}>
              WebDev
              <Typography component="span" variant="caption"
                          sx={{ opacity: .55, fontSize: 11 }}>
                (v{status.version || "…"})
              </Typography>
              <ConnBadge conn={conn} showVer={false} />
            </Typography>
            {multiMode && (
              <ProjectSelect projects={projects} current={project}
                             onChange={selectProject}
                             onAdd={() => setAddOpen(true)} />
            )}
            <Box sx={{ mr: "auto" }} />
            <Typography variant="body2"
              sx={{ display: { xs: "none", md: "block" }, opacity: .9,
                    fontSize: 13 }}>
              {statusText}
            </Typography>
            {status.current_task && (
              <Button size="small" variant="outlined" color="inherit"
                      onClick={() => setConfirm({ kind: "stop",
                        name: status.current_task })}
                      sx={{ borderColor: "rgba(255,255,255,.55)",
                            color: "#ffcdd2", fontSize: 11, px: 1,
                            whiteSpace: "nowrap" }}>
                ⛔ Стоп
              </Button>
            )}
            <Box sx={{ display: { xs: "none", sm: "flex" }, gap: 1 }}
                 onFocus={() => modelFocus.current = true}
                 onBlur={() => modelFocus.current = false}>
              <ModelSelect models={models.models} current={models.current}
                           onChange={setModel} />
            </Box>
            <Box sx={{ display: { xs: "none", sm: "flex" } }}
                 onFocus={() => modeFocus.current = true}
                 onBlur={() => modeFocus.current = false}>
              <ModeSelect mode={mode} onChange={setModeApi} />
            </Box>
            <Tooltip title="профиль">
              <IconButton color="inherit" onClick={() => setProfileOpen(true)}>
                <PersonIcon />
              </IconButton>
            </Tooltip>
            <Tooltip title="выйти">
              <IconButton color="inherit" onClick={logout}>
                <LogoutIcon />
              </IconButton>
            </Tooltip>
          </Toolbar>
        </AppBar>
        {/* spacer — AppBar is position:fixed, header stays pinned on top */}
        <Toolbar variant="dense" />

        <SwipeableDrawer open={drawerOpen}
                onOpen={() => setDrawerOpen(true)}
                onClose={() => setDrawerOpen(false)}
                swipeAreaWidth={24}
                ModalProps={{ keepMounted: true }}
                disableSwipeToOpen={
                  /iPad|iPhone|iPod/.test(navigator.userAgent)}
                sx={{ display: { md: "none" } }}>
          {drawer}
        </SwipeableDrawer>

        <Box sx={{ flex: 1, display: "flex", width: "100%", maxWidth: 1280,
                   mx: "auto" }}>
          <Box sx={{ flex: 1, minWidth: 0, p: "16px 12px 150px" }}>
            {loadingOlder &&
              <Typography align="center" color="text.secondary" sx={{ py: 1 }}>
                загружаю ранние…</Typography>}
            {items.length
              ? items.map(t => <TaskCard key={t.stem} t={t}
                    onCommit={commitAct}
                    onStop={t2 => setConfirm({ kind: "stop", name: t2.name })}
                    onCancel={t2 => setConfirm({ kind: "cancel",
                                    name: t2.name, stem: t2.stem })} />)
              : <Typography align="center" color="text.secondary"
                  sx={{ mt: 8 }}>Задач пока нет — напиши первую внизу.</Typography>}
          </Box>
          <Paper elevation={1} sx={{
            width: 290, flexShrink: 0, m: "16px 12px 150px 4px",
            display: { xs: "none", md: "flex" }, flexDirection: "column",
            alignSelf: "flex-start", position: "sticky", top: 72,
            maxHeight: "calc(100vh - 92px)", borderRadius: 2,
            overflow: "hidden" }}>
            <Box sx={{ px: 1.5, py: 1, fontWeight: 500, fontSize: 13,
                       borderBottom: "1px solid #eee", display: "flex",
                       alignItems: "center", gap: 0.8 }}>
              <FolderOpenIcon sx={{ fontSize: 18 }} /> Файлы проекта
              <IconButton size="small" sx={{ ml: "auto" }} title="обновить"
                          onClick={() => setTreeVer(v => v + 1)}>
                <RefreshIcon sx={{ fontSize: 18 }} />
              </IconButton>
            </Box>
            <FileTree key={project + ":" + treeVer}
                      project={project} onError={setToast}
                      onOpenFile={setEditPath} />
            <Divider />
            <Changes project={project} toast={setToast} />
          </Paper>
        </Box>

        <Composer project={project} sttStatus={status.stt_status}
                  toast={setToast} onSent={loadTasks}
                  conn={conn} onOpenDrawer={() => setDrawerOpen(true)} />
      </Box>

      <FileEditor project={project} path={editPath}
                  onClose={() => setEditPath(null)} toast={setToast} />
      <AddProject open={addOpen} onClose={() => setAddOpen(false)}
                  onAdded={f => { refreshProjects()
                    .then(() => selectProject(f)); }} />


      <Dialog open={!!confirm} onClose={() => setConfirm(null)}
              maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontSize: 16 }}>
          {confirm?.kind === "stop" ? "Остановить задачу?"
                                   : "Удалить задачу из очереди?"}
        </DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            {confirm?.kind === "stop"
              ? `«${confirm.name}» будет принудительно убита — воркер ` +
                "возьмёт следующую из очереди. Незакоммиченные изменения " +
                "в репо останутся."
              : `«${confirm?.name}» будет удалена из очереди и не ` +
                "выполнится. Действие необратимо."}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirm(null)}>Отмена</Button>
          <Button color="error" variant="contained" onClick={confirmAct}>
            {confirm?.kind === "stop" ? "Остановить" : "Удалить"}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={profileOpen} onClose={() => setProfileOpen(false)}
              maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontSize: 16 }}>Смена пароля</DialogTitle>
        <DialogContent sx={{ display: "flex", flexDirection: "column",
                             gap: 2, pt: "8px !important" }}>
          <TextField label="Текущий пароль" type="password" size="small"
                     autoComplete="current-password" value={pw.cur}
                     onChange={e => setPw({ ...pw, cur: e.target.value })} />
          <TextField label="Новый пароль (мин. 6 символов)" type="password"
                     size="small" autoComplete="new-password" value={pw.n1}
                     onChange={e => setPw({ ...pw, n1: e.target.value })} />
          <TextField label="Новый пароль ещё раз" type="password" size="small"
                     autoComplete="new-password" value={pw.n2}
                     onChange={e => setPw({ ...pw, n2: e.target.value })} />
        </DialogContent>
        <DialogActions>
          <Button variant="contained" onClick={savePw}>Сохранить</Button>
        </DialogActions>
      </Dialog>

      <Snackbar open={!!toast || !!toastNode} autoHideDuration={6000}
                onClose={() => { setToast(null); setToastNode(null); }}
                message={toastNode || toast} />
      </ErrBoundary>
    </ThemeProvider>
  );
}

// PWA: registers /sw.js so Chrome offers "Install app" (see manifest link)
if ("serviceWorker" in navigator)
  navigator.serviceWorker.register("/sw.js").catch(() => {});

createRoot(document.getElementById("root")).render(<App />);
