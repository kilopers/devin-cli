// «Изменения» — collapsible section under the file tree listing git-dirty
// files of the project (GET /api/diff, polled). Click → fullscreen dialog
// with the unified diff, syntax-highlighted via hljs' "diff" language
// (additions green, deletions red — same palette as github-dark).
import { useEffect, useRef, useState } from "react";
import {
  Alert, AppBar, Box, Chip, Collapse, Dialog, IconButton, ListItemButton,
  Toolbar, Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import CancelIcon from "@mui/icons-material/Cancel";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import CircularProgress from "@mui/material/CircularProgress";
import Popover from "@mui/material/Popover";
import Tooltip from "@mui/material/Tooltip";
import hljs from "highlight.js/lib/common";
import { apiJson } from "./api.js";

const STATUS_COLOR = { M: "#e6a23c", A: "#2e7d32", D: "#c62828",
                       R: "#1565c0", "??": "#2e7d32" };

// Last CI run icon (GitHub Actions / GitLab pipeline via GET /api/build).
const BUILD_UI = {
  success:  { Icon: CheckCircleIcon, color: "#2e7d32", label: "успех" },
  failed:   { Icon: ErrorIcon,       color: "#c62828", label: "упала" },
  running:  { Icon: null,            color: "#e6a23c", label: "идёт" },
  canceled: { Icon: CancelIcon,      color: "#9aa0a6", label: "отменена" },
  unknown:  { Icon: WarningAmberIcon, color: "#9aa0a6",
              label: "статус неизвестен" },
};

function BuildIcon({ build }) {
  const [anchor, setAnchor] = useState(null);   // popover with full error
  if (!build) return null;

  // the icon sits in a circled IconButton — visibly clickable
  const circleBtn = (color, title, onClick, children) => (
    <Tooltip title={title}>
      <IconButton size="small" onClick={onClick}
                  sx={{ width: 24, height: 24, p: 0,
                        border: `1.5px solid ${color}`,
                        "&:hover": { bgcolor: color + "22" } }}>
        {children}
      </IconButton>
    </Tooltip>
  );

  if (build.error)
    return (
      <>
        {circleBtn("#e6a23c", "Ошибка проверки сборки — нажми для деталей",
                   e => { e.stopPropagation(); setAnchor(e.currentTarget); },
                   <WarningAmberIcon sx={{ fontSize: 15,
                                          color: "#e6a23c" }} />)}
        <Popover open={!!anchor} anchorEl={anchor}
                 onClose={() => setAnchor(null)}
                 anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
                 transformOrigin={{ vertical: "top", horizontal: "right" }}
                 onClick={e => e.stopPropagation()}>
          <Box sx={{ p: 1.5, maxWidth: 380 }}>
            <Typography variant="subtitle2" sx={{ fontSize: 13 }}>
              Ошибка проверки сборки
            </Typography>
            <Typography variant="body2" sx={{
              mt: 0.5, fontSize: 12, whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontFamily: "ui-monospace, Menlo, monospace" }}>
              {build.error}
            </Typography>
          </Box>
        </Popover>
      </>
    );

  const ui = BUILD_UI[build.status];
  if (!ui) return null;                       // "none" — remote без CI
  const tip = `${build.provider === "gitlab" ? "GitLab" : "GitHub"} ` +
              `сборка: ${ui.label}` +
              (build.ref ? ` (${build.ref})` : "") +
              (build.url ? " — открыть" : "");
  return circleBtn(
    ui.color, tip,
    e => { e.stopPropagation();
           if (build.url) window.open(build.url, "_blank"); },
    ui.Icon ? <ui.Icon sx={{ fontSize: 15, color: ui.color }} />
            : <CircularProgress size={12} thickness={6}
                                sx={{ color: ui.color }} />);
}

const fmtWhen = iso => {
  const t = iso && new Date(iso);
  return t && !isNaN(t)
    ? t.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit",
                                  hour: "2-digit", minute: "2-digit" })
    : "";
};

// «Сборки» — collapsible list of the last ~6 CI runs (build.runs).
function BuildsPanel({ build, open, onToggle, project }) {
  const runs = build?.runs;
  const [jobsFor, setJobsFor] = useState(null);   // stem прогона
  const [jobs, setJobs] = useState({});           // runId -> {loading, list, error}

  const toggleJobs = async r => {
    const rid = r.id || r.num;
    if (jobsFor === rid) { setJobsFor(null); return; }
    setJobsFor(rid);
    if (jobs[rid]) return;
    setJobs(m => ({ ...m, [rid]: { loading: true } }));
    try {
      const d = await apiJson("/api/build/jobs?project=" +
        encodeURIComponent(project || "") + "&id=" + rid);
      setJobs(m => ({ ...m, [rid]: d.ok
        ? { list: d.jobs } : { error: d.error || "ошибка" } }));
    } catch (e) {
      setJobs(m => ({ ...m, [rid]: { error: String(e) } }));
    }
  };
  if (!runs || !runs.length) return null;
  return (
    <>
      <ListItemButton dense onClick={onToggle}
                      sx={{ px: 1.5, py: 0.5 }}>
        {open ? <ExpandLessIcon sx={{ fontSize: 18 }} />
               : <ExpandMoreIcon sx={{ fontSize: 18 }} />}
        <Typography variant="body2" sx={{ fontWeight: 500, ml: 0.5 }}>
          Сборки
        </Typography>
        <Chip size="small" label={runs.length}
              sx={{ ml: 1, height: 18, fontSize: 11 }} />
      </ListItemButton>
      <Collapse in={open}>
        <Box>
          {runs.map((r, i) => {
            const ui = BUILD_UI[r.status] || BUILD_UI.unknown;
            const rid = r.id || r.num;
            const openJ = jobsFor === rid;
            const j = jobs[rid];
            return (
              <Box key={r.url || i}>
                <ListItemButton dense
                  onClick={() => toggleJobs(r)}
                  sx={{ px: 1.5, py: 0.4, gap: 0.7 }}>
                  {ui.Icon
                    ? <ui.Icon sx={{ fontSize: 15, color: ui.color,
                                     flexShrink: 0 }} />
                    : <CircularProgress size={11} thickness={6}
                                        sx={{ color: ui.color,
                                              flexShrink: 0 }} />}
                  <Typography variant="body2" noWrap sx={{
                    flex: 1, fontSize: 12.5,
                    fontFamily: "ui-monospace, Menlo, monospace" }}>
                    {r.name}{r.num ? ` #${r.num}` : ""}
                    {r.ref ? ` · ${r.ref}` : ""}
                  </Typography>
                  <ExpandMoreIcon sx={{
                    fontSize: 15, color: "#9aa0a6", flexShrink: 0,
                    transform: openJ ? "rotate(180deg)" : "none",
                    transition: "transform .2s" }} />
                  <Typography variant="caption" color="text.secondary"
                              sx={{ fontSize: 10.5, flexShrink: 0 }}>
                    {fmtWhen(r.when)}
                  </Typography>
                </ListItemButton>
                {openJ && (
                  <Box sx={{ pl: 4.5, pr: 1.5, pb: 0.4 }}>
                    {!j || j.loading ? (
                      <CircularProgress size={12} thickness={6}
                                        sx={{ my: 0.4 }} />
                    ) : j.error ? (
                      <Typography variant="caption" color="error">
                        {j.error}
                      </Typography>
                    ) : !j.list || !j.list.length ? (
                      <Typography variant="caption" color="text.secondary">
                        джобов нет
                      </Typography>
                    ) : j.list.map((jb, k) => {
                      const ju = BUILD_UI[jb.status] || BUILD_UI.unknown;
                      return (
                        <Box key={k} sx={{ display: "flex", py: 0.2,
                                          gap: 0.7, alignItems: "center",
                                          cursor: jb.url ? "pointer"
                                                         : "default" }}
                          onClick={() => jb.url &&
                            window.open(jb.url, "_blank")}>
                          {ju.Icon
                            ? <ju.Icon sx={{ fontSize: 13, color: ju.color,
                                             flexShrink: 0 }} />
                            : <CircularProgress size={10} thickness={6}
                                                sx={{ color: ju.color,
                                                      flexShrink: 0 }} />}
                          <Typography variant="caption" noWrap sx={{
                            flex: 1, fontSize: 11.5,
                            fontFamily: "ui-monospace, Menlo, monospace" }}>
                            {jb.name}
                          </Typography>
                          <Typography variant="caption"
                            color="text.secondary"
                            sx={{ fontSize: 10, flexShrink: 0 }}>
                            {jb.sec != null ? `${Math.round(jb.sec)}с` : ""}
                            {jb.when ? " " + fmtWhen(jb.when) : ""}
                          </Typography>
                        </Box>
                      );
                    })}
                  </Box>
                )}
              </Box>
            );
          })}
        </Box>
      </Collapse>
    </>
  );
}

function DiffView({ text }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (el) {
      el.textContent = text;
      try { hljs.highlightElement(el); } catch (e) {}
    }
  }, [text]);
  return (
    <Box component="pre" sx={{
      m: 0, p: 2, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
      fontSize: 12.5, lineHeight: 1.45, whiteSpace: "pre", overflow: "auto",
      flex: 1, bgcolor: "#0d1117", color: "#c9d1d9",
      "& .hljs-addition": { bgcolor: "rgba(46,160,67,.15)",
        color: "#aff5b4", display: "block" },
      "& .hljs-deletion": { bgcolor: "rgba(248,81,73,.15)",
        color: "#ffdcd7", display: "block" },
    }}>
      <code ref={ref} className="language-diff" />
    </Box>
  );
}


// «Вебхуки» — последние 7 доставок хуков репозитория (GitHub/GitLab).
// Хуков нет → секция не рендерится вовсе.
export function Webhooks({ project, open, onToggle }) {
  const [data, setData] = useState(null);
  const projRef = useRef(project);
  projRef.current = project;

  useEffect(() => {
    setData(null);
    let live = true;
    const load = async () => {
      try {
        const d = await apiJson("/api/webhooks?project=" +
          encodeURIComponent(projRef.current || ""));
        if (live) setData(d);
      } catch (e) { if (live) setData({ ok: false }); }
    };
    load();
    const t = setInterval(load, 60000);  // серверный кэш 60 с
    return () => { live = false; clearInterval(t); };
  }, [project]);

  const hooks = (data && data.hooks) || [];
  if (!hooks.length) return null;
  const delivs = hooks
    .flatMap(h => (h.deliveries || [])
      .map(d => ({ ...d, hook: h.name })))
    .sort((a, b) => (b.when || "").localeCompare(a.when || ""))
    .slice(0, 7);

  const host = n => {
    try { return new URL(n).host; } catch (e) { return n; }
  };

  return (<>
    <ListItemButton dense onClick={onToggle} sx={{ px: 1.5, py: 0.5 }}>
      {open ? <ExpandLessIcon sx={{ fontSize: 18 }} />
            : <ExpandMoreIcon sx={{ fontSize: 18 }} />}
      <Typography variant="body2" sx={{ fontWeight: 500, ml: 0.5 }}>
        Вебхуки
      </Typography>
      <Chip size="small" label={hooks.length}
            sx={{ ml: 1, height: 18, fontSize: 11 }} />
    </ListItemButton>
    <Collapse in={open}>
      <Box>
        {data && !data.ok ? (
          <Typography variant="caption" color="error"
                      sx={{ px: 2, py: 0.5, display: "block" }}>
            {data.error || "ошибка"}
          </Typography>
        ) : delivs.length === 0 ? (
          <Typography variant="caption" color="text.secondary"
                      sx={{ px: 2, py: 0.5, display: "block" }}>
            {hooks.map(h => host(h.name)).join(", ")} — доставок пока нет
          </Typography>
        ) : delivs.map((d, i) => (
          <Box key={i} sx={{ px: 1.5, py: 0.3, display: "flex",
                            alignItems: "center", gap: 0.7 }}>
            {d.ok
              ? <CheckCircleIcon sx={{ fontSize: 15, color: "#2e7d32",
                                       flexShrink: 0 }} />
              : <ErrorIcon sx={{ fontSize: 15, color: "#c62828",
                                 flexShrink: 0 }} />}
            <Typography variant="body2" noWrap sx={{
              flex: 1, fontSize: 12.5,
              fontFamily: "ui-monospace, Menlo, monospace" }}>
              {d.event || "?"} · {host(d.hook)}
            </Typography>
            <Typography variant="caption" color="text.secondary"
                        sx={{ fontSize: 10.5, flexShrink: 0 }}>
              {d.code || "—"} · {fmtWhen(d.when)}
            </Typography>
          </Box>
        ))}
      </Box>
    </Collapse>
  </>);
}

export default function Changes({ project, toast, open, onToggle,
                                  bOpen, bToggle }) {
  const [entries, setEntries] = useState([]);
  const [err, setErr] = useState(null);
  const [diff, setDiff] = useState(null);  // {path, diff?, error?}
  const [build, setBuild] = useState(null);
  const projRef = useRef(project);
  projRef.current = project;

  useEffect(() => {
    setEntries([]); setErr(null); setBuild(null);
    const load = async () => {
      try {
        const d = await apiJson("/api/diff?project=" +
          encodeURIComponent(projRef.current || ""));
        if (d.ok) { setEntries(d.entries); setErr(null); }
        else setErr(d.error || "ошибка");
      } catch (e) {
        // e.g. old backend without /api/diff (404 → HTML, not JSON)
        setErr("API недоступен");
      }
    };
    const loadBuild = async () => {
      try {
        const d = await apiJson("/api/build?project=" +
          encodeURIComponent(projRef.current || ""));
        setBuild(d);
      } catch (e) { /* icon just stays as it was */ }
    };
    load(); loadBuild();
    const t = setInterval(load, 5000);
    const tb = setInterval(loadBuild, 30000);  // server caches 60 s anyway
    return () => { clearInterval(t); clearInterval(tb); };
  }, [project]);

  const openFile = async path => {
    setDiff({ path, diff: null });
    try {
      const d = await apiJson("/api/diff/file?project=" +
        encodeURIComponent(projRef.current || "") +
        "&path=" + encodeURIComponent(path));
      setDiff({ path, diff: d.diff, error: d.ok ? null : d.error });
    } catch (e) {
      setDiff({ path, diff: null, error: String(e) });
    }
  };

  return (
    <>
      <ListItemButton dense onClick={onToggle}
                      sx={{ px: 1.5, py: 0.5 }}>
        {open ? <ExpandLessIcon sx={{ fontSize: 18 }} />
               : <ExpandMoreIcon sx={{ fontSize: 18 }} />}
        <Typography variant="body2" sx={{ fontWeight: 500, ml: 0.5 }}>
          Изменения
        </Typography>
        <Chip size="small" label={entries.length}
              sx={{ ml: 1, height: 18, fontSize: 11 }} />
        <Box sx={{ ml: "auto", display: "flex", alignItems: "center" }}>
          <BuildIcon build={build} />
        </Box>
      </ListItemButton>
      <Collapse in={open}>
        <Box>
          {err ? (
            <Typography variant="caption" color="error"
                        sx={{ px: 2, py: 0.5, display: "block" }}>
              {err}
            </Typography>
          ) : entries.length === 0 ? (
            <Typography variant="caption" color="text.secondary"
                        sx={{ px: 2, py: 0.5, display: "block" }}>
              чисто — изменений нет
            </Typography>
          ) : entries.map(e => (
            <ListItemButton key={e.path} dense
                            onClick={() => openFile(e.path)}
                            sx={{ px: 1.5, py: 0.3 }}>
              <Box component="span" sx={{
                fontSize: 10, fontWeight: 700, width: 16, flexShrink: 0,
                color: STATUS_COLOR[e.status] || "#9aa0a6" }}>
                {e.status === "??" ? "?" : e.status[0]}
              </Box>
              <Typography variant="body2" noWrap
                          sx={{ fontSize: 12.5, fontFamily:
                            "ui-monospace, Menlo, monospace" }}>
                {e.path}
              </Typography>
            </ListItemButton>
          ))}
        </Box>
      </Collapse>

      <BuildsPanel build={build} open={bOpen} onToggle={bToggle}
              project={project} />

      <Dialog fullScreen open={!!diff} onClose={() => setDiff(null)}>
        <AppBar position="sticky" color="primary">
          <Toolbar variant="dense" sx={{ gap: 1 }}>
            <IconButton color="inherit" onClick={() => setDiff(null)}>
              <CloseIcon />
            </IconButton>
            <Typography variant="body2" noWrap sx={{
              fontFamily: "ui-monospace, Menlo, monospace", fontSize: 13 }}>
              {diff?.path}
            </Typography>
          </Toolbar>
        </AppBar>
        <Box sx={{ display: "flex", flexDirection: "column", flex: 1,
                   minHeight: 0 }}>
          {diff?.error ? (
            <Alert severity="error" sx={{ m: 2 }}>{diff.error}</Alert>
          ) : diff?.diff === null ? (
            <Typography sx={{ p: 2 }} color="text.secondary">
              загрузка…</Typography>
          ) : diff?.diff === "" ? (
            <Typography sx={{ p: 2 }} color="text.secondary">
              пустой diff</Typography>
          ) : (
            <DiffView text={diff?.diff || ""} />
          )}
        </Box>
      </Dialog>
    </>
  );
}
