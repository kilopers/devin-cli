// Devin Worker web UI — React + MUI (was: Materialize + vanilla JS).
// Same JSON API as before; polling every 3 s, infinite scroll-up feed.
import React, { useCallback, useEffect, useLayoutEffect, useMemo,
                useRef, useState }
  from "react";
import { createRoot } from "react-dom/client";
import { createTheme, ThemeProvider } from "@mui/material/styles";
import {
  Alert, AppBar, Box, Button, Card, CardContent, Chip, Collapse,
  CssBaseline, Dialog, DialogActions, DialogContent, DialogTitle,
  Divider, GlobalStyles, IconButton, ListItemButton,
  ListSubheader, Menu, MenuItem, Paper, Select, Skeleton, Snackbar,
  SwipeableDrawer, TextField, Toolbar, Tooltip, Typography,
} from "@mui/material";
import MicIcon from "@mui/icons-material/Mic";
import StopIcon from "@mui/icons-material/Stop";
import AddIcon from "@mui/icons-material/Add";
import { STT_RATE, resample, encodeWav } from "./audio.js";
import PersonIcon from "@mui/icons-material/Person";
import LogoutIcon from "@mui/icons-material/Logout";
import KeyIcon from "@mui/icons-material/VpnKey";
import LockIcon from "@mui/icons-material/Lock";
import SettingsIcon from "@mui/icons-material/Settings";
import RepoKeys from "./RepoKeys.jsx";
import Settings from "./Settings.jsx";
import Workspaces, { Dot as WsDot } from "./Workspaces.jsx";
import ProjectSettings from "./ProjectSettings.jsx";
import TuneIcon from "@mui/icons-material/Tune";
import ModelsPage from "./ModelsPage.jsx";
import WorkspacesIcon from "@mui/icons-material/Layers";
import Users from "./Users.jsx";
import PeopleIcon from "@mui/icons-material/People";
import FolderOpenIcon from "@mui/icons-material/FolderOpen";
import RefreshIcon from "@mui/icons-material/Refresh";

import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import AccountTreeIcon from "@mui/icons-material/AccountTree";
import AttachFileIcon from "@mui/icons-material/AttachFile";
import CloseIcon from "@mui/icons-material/Close";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import CheckIcon from "@mui/icons-material/Check";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import ForumOutlinedIcon from "@mui/icons-material/ForumOutlined";
import DeleteOutlinedIcon from "@mui/icons-material/DeleteOutlined";
import ReplayIcon from "@mui/icons-material/Replay";
import RedoIcon from "@mui/icons-material/Redo";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import DragIndicatorIcon from "@mui/icons-material/DragIndicator";
import DriveFileMoveIcon from "@mui/icons-material/DriveFileMove";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import Grid from "@mui/material/Grid";
import useMediaQuery from "@mui/material/useMediaQuery";
import { api, apiJson, post } from "./api.js";
import Markdown from "./Markdown.jsx";
import FileTree from "./FileTree.jsx";
import Changes, { Webhooks, Branches, Deploy } from "./Changes.jsx";
import Instr from "./Instr.jsx";
import FileEditor from "./FileEditor.jsx";
import AddProject from "./AddProject.jsx";
import RepoBrowse from "./RepoBrowse.jsx";
import Composer from "./Composer.jsx";
import TopicSettings from "./TopicSettings.jsx";
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

// Дизайн-система панели: светлая нейтральная тема в духе Linear/Vercel —
// Inter, один акцент (#5e6ad2), скругления 10–14, тонкие границы,
// минимум теней. Акцент шапки/кнопок всё ещё динамический — цвет
// проекта/пространства (см. accent в App).
const FONT = '"Inter", "Segoe UI", system-ui, -apple-system, ' +
             '"Helvetica Neue", Arial, sans-serif';
const theme = createTheme({
  palette: {
    primary: { main: "#5e6ad2" },
    background: { default: "#f6f7fa", paper: "#ffffff" },
    text: { primary: "#1c2128", secondary: "#5d6673" },
    divider: "rgba(28,33,40,.09)",
  },
  typography: {
    fontFamily: FONT,
    button: { textTransform: "none" },
    h6: { fontWeight: 600 },
  },
  // единый «карточный» стиль: скругления и мягкие контуры везде
  shape: { borderRadius: 10 },
  components: {
    MuiCard: { styleOverrides: { root: ({ theme: t }) => ({
      borderRadius: 14, boxShadow: "none",
      border: `1px solid ${t.palette.divider}` }) } },
    MuiDialog: { styleOverrides: { paper: ({ theme: t }) => ({
      borderRadius: 14,
      border: `1px solid ${t.palette.divider}`,
      boxShadow: "0 16px 48px rgba(16,24,40,.16)" }) } },
    MuiPaper: { styleOverrides: {
      root: { backgroundImage: "none" } } },
    MuiAppBar: { defaultProps: { elevation: 0 } },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: { root: {
        textTransform: "none", borderRadius: 9, fontWeight: 500 } } },
    MuiChip: { styleOverrides: { root: {
      borderRadius: 8, fontWeight: 500 } } },
    MuiOutlinedInput: { styleOverrides: { root: {
      borderRadius: 10 } } },
    MuiPopover: { styleOverrides: { paper: ({ theme: t }) => ({
      borderRadius: 12, border: `1px solid ${t.palette.divider}`,
      boxShadow: "0 8px 28px rgba(16,24,40,.12)" }) } },
    MuiTooltip: { styleOverrides: { tooltip: {
      borderRadius: 7, fontSize: 11.5, bgcolor: "#1c2128" } } },
    MuiAlert: { styleOverrides: { root: { borderRadius: 10 } } },
    MuiSnackbar: { styleOverrides: { root: {
      "& .MuiSnackbarContent-root": { borderRadius: 10 } } } },
  },
});
const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";
const STATUS_RU = { queued: "в очереди", running: "выполняется",
                    done: "готово", note: "заметка" };
const SRC_RU = { telegram: "telegram", web: "web", file: "файл" };
const fmtNum = n => (n ?? 0).toLocaleString("ru-RU");
const fmtDur = s => s == null ? null
  : s >= 3600 ? `${Math.floor(s / 3600)}ч ${Math.round(s % 3600 / 60)}м`
  : s >= 60 ? `${Math.floor(s / 60)}м ${s % 60}с`
  : `${s}с`;

const mdStyles = {
  body: { background: "#f6f7fa" },
  // два подряд разделителя (секция вернула null) — показываем один
  ".MuiDivider-root + .MuiDivider-root": { display: "none" },
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
    "& a": { color: "#5e6ad2" },
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

// время выполнения задачи: от старта Devin (tasks.started — очередь
// не считается) до готовности; у идущей тикает каждую секунду своим
// стейтом — memo(TaskCard) при этом не перерисовывается;
// у старых карточек без started — ничего
function Elapsed({ started, finished }) {
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    if (finished || !started) return undefined;
    const iv = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(iv);
  }, [started, finished]);
  if (!started) return null;
  const s = Math.max(0, Math.floor(
    ((finished ? finished * 1000 : now) - started * 1000) / 1000));
  const hh = Math.floor(s / 3600), mm = Math.floor(s / 60) % 60,
        ss = s % 60;
  const pad = n => String(n).padStart(2, "0");
  return (
    <Tooltip title="время выполнения — от старта Devin до готовности, очередь не считается">
      <Chip size="small" variant="outlined"
            color={finished ? "default" : "info"}
            sx={{ height: 18, fontSize: 10, fontWeight: 600, ml: 0.4,
                  borderRadius: "7px", fontFamily: MONO,
                  "& .MuiChip-label": { px: "5px" } }}
            label={hh ? `${hh}:${pad(mm)}:${pad(ss)}`
                      : `${mm}:${pad(ss)}`} />
    </Tooltip>);
}

// текущее VPN-подключение mihomo в шапке: чип с выбранной нодой,
// меню-переключатель и кнопка замера задержек (пул по 6, прогресс
// «N из M» прямо на месте иконки); mihomo API недоступен — не рисуем
function ProxySel() {
  const [info, setInfo] = useState(null);
  const [delays, setDelays] = useState({});
  const [prog, setProg] = useState(null);
  const [anchor, setAnchor] = useState(null);
  useEffect(() => {
    fetch("/api/mihomo").then(r => r.json())
      .then(d => setInfo(d.ok ? d : { on: false }))
      .catch(() => setInfo({ on: false }));
  }, []);
  if (!info || !info.on) return null;
  const ping = async () => {
    if (prog) return;
    const nodes = info.nodes || [];
    setProg({ done: 0, total: nodes.length });
    let done = 0;
    const step = async name => {
      try {
        const r = await fetch("/api/mihomo/delay?name=" +
                              encodeURIComponent(name))
          .then(r => r.json());
        setDelays(m => ({ ...m, [name]: r.delay || 0 }));
      } catch { setDelays(m => ({ ...m, [name]: 0 })); }
      done += 1;
      setProg(p => p && { total: p.total, done });
    };
    for (let i = 0; i < nodes.length; i += 6)
      await Promise.all(nodes.slice(i, i + 6).map(step));
    setProg(null);
  };
  const choose = name => {
    setAnchor(null);
    fetch("/api/mihomo/select", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }) })
      .then(r => r.json())
      .then(d => d.ok && setInfo(i => ({ ...i, now: name })))
      .catch(() => {});
  };
  const cur = delays[info.now];
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 0.3,
               flexShrink: 0 }}>
      <Tooltip title={`VPN mihomo «${info.group}» — нажмите, чтобы переключить ноду`}>
        <Chip size="small" variant="outlined"
              onClick={e => setAnchor(e.currentTarget)}
              label={"🌐 " + info.now + (cur ? ` · ${cur} мс` : "")}
              sx={{ height: 22, fontSize: 11, color: "#fff",
                    borderColor: "rgba(255,255,255,.55)",
                    maxWidth: 220,
                    "& .MuiChip-label": { px: "8px", overflow: "hidden",
                                          textOverflow: "ellipsis" } }} />
      </Tooltip>
      <Tooltip title={prog ? `опрос нод — ${prog.done} из ${prog.total}`
                           : "замерить задержку всех нод"}>
        <IconButton size="small" color="inherit" disabled={!!prog}
                    onClick={ping} sx={{ p: 0.3 }}>
          {prog
            ? <Typography sx={{ fontSize: 10, color: "#fff",
                                fontFamily: MONO, minWidth: 40,
                                textAlign: "center" }}>
                {prog.done}/{prog.total}
              </Typography>
            : <RefreshIcon sx={{ fontSize: 16 }} />}
        </IconButton>
      </Tooltip>
      <Menu anchorEl={anchor} open={!!anchor}
            onClose={() => setAnchor(null)}
            PaperProps={{ sx: { maxHeight: 420 } }}>
        {(info.nodes || []).map(n =>
          <MenuItem key={n} dense selected={n === info.now}
                    onClick={() => choose(n)}
                    sx={{ fontSize: 12.5, gap: 1 }}>
            <Box component="span" sx={{ flexGrow: 1 }}>{n}</Box>
            <Typography component="span"
                        sx={{ fontSize: 11, fontFamily: MONO,
                              color: delays[n] ? "success.main"
                                               : "text.disabled" }}>
              {delays[n] === undefined ? ""
                 : delays[n] ? `${delays[n]} мс` : "✕"}
            </Typography>
          </MenuItem>)}
      </Menu>
    </Box>);
}

function StatusChip({ t }) {
  const failed = t.status === "done" && t.task_status &&
    !/exit code: 0/.test(t.task_status);
  // «starting» — devin-task ещё готовится (прокси/git/auth), сам Devin
  // не начал работать: бейдж светлее и подпись «запускается»
  const starting = t.status === "running" && t.starting;
  const color = failed || t.status === "running"
    ? (failed ? "error" : "info") : (t.status === "done" ? "success" : "default");
  return <Chip size="small" color={color}
    variant={starting ? "outlined" : "filled"}
    sx={{ height: 24, fontSize: 12,
          // у running слева спиннер (margin-right -4px у MUI) —
          // зазор иконка→текст выходит меньше правого паддинга:
          // pl лейбла 12px — внутри бейджа слева/справа ровно
          ...(t.status === "running"
            ? { "& .MuiChip-label": { pl: "12px" } } : {}) }}
    label={failed ? "ошибка"
                : starting ? "запускается"
                           : (STATUS_RU[t.status] || t.status)}
    icon={t.status === "running"
      ? <Box component="span" sx={{ width: 10, height: 10, ml: "4px",
          border: "2px solid #90caf9", borderTopColor: "transparent",
          borderRadius: "50%", animation: "rot .8s linear infinite",
          "@keyframes rot": { to: { transform: "rotate(360deg)" } } }} />
      : undefined} />;
}

const TRANSLIT = { "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e",
  "ж":"zh","з":"z","и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o",
  "п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"h","ц":"c","ч":"ch",
  "ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya" };
const branchSlug = s => s.toLowerCase().split("")
  .map(ch => TRANSLIT[ch] !== undefined ? TRANSLIT[ch]
           : /[a-z0-9]/.test(ch) ? ch : "-").join("")
  .replace(/-+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
const branchSuggest = prompt => {
  const first = (prompt || "").trim().split("\n")[0] || "";
  const slug = branchSlug(first) || "changes";
  const d = new Date();
  const mmdd = String(d.getMonth() + 1).padStart(2, "0")
             + String(d.getDate()).padStart(2, "0");
  return `task/${slug}-${mmdd}`;
};

// выбор темы запоминаем per-проект: переживает переключения проектов
// и закрытие приложения; «главная» в карту не пишется
const TOPIC_LS = "devin.topic.sel";
const loadTopicMap = () => {
  try { return JSON.parse(localStorage.getItem(TOPIC_LS)) || {}; }
  catch { return {}; }
};
const saveTopicSel = (p, v) => {
  if (!p) return;
  const m = loadTopicMap();
  if (v === "main") delete m[p]; else m[p] = String(v);
  try { localStorage.setItem(TOPIC_LS, JSON.stringify(m)); } catch {}
};

// скелетон поверх карточки/колонки, пока действие идёт на сервере:
// UI меняется только после ответа бэка и перечитки ленты
// stem+тип карточки, которую тащат прямо сейчас — в dragover
// payload dataTransfer недоступен, а мержу нужна «note на note»
let dragStemNow = null;

const PendOverlay = () => (
  <Box onClick={e => e.stopPropagation()} sx={{
    position: "absolute", inset: 0, zIndex: 3, borderRadius: "inherit",
    overflow: "hidden", cursor: "progress",
    bgcolor: "rgba(246,247,250,.55)" }}>
    <Skeleton variant="rectangular" animation="wave"
      sx={{ width: "100%", height: "100%",
            bgcolor: "rgba(94,106,210,.08)" }} />
  </Box>);

const TaskCard = React.memo(function TaskCard({ t, onStop, onCancel,
                                               onDel, toast, hideTopic,
                                               sel, onNote, onCont, cols,
                                               onDict, dictOn, pending,
                                               pend, onGone,
                                               mergeSel, onMergeOver,
                                               onMergeDrop,
                                               onMergeLeave }) {
  // свёрнута: ~3 строки задачи; «подробнее» появляется только когда
  // текст реально обрезан или у неуспешной задачи есть вывод
  const [open, setOpen] = useState(false);
  // prompt с бэкенда — превью (2000): полный текст догружаем по кнопке
  const [full, setFull] = useState(null);
  const [copied, setCopied] = useState(false);
  const loadFull = () =>
    apiJson("/api/task/" + t.stem + "/prompt")
      .then(d => { if (d.ok) setFull(d.prompt); })
      .catch(() => {});
  const promptShown = full !== null ? full : t.prompt;
  const maybeCut = full === null && (t.prompt || "").length >= 2000;
  // «инфо» — статистика завершённой задачи (tasks.stats + длительность)
  const [info, setInfo] = useState(false);
  // «результат/вывод» — модалка с выводом Devin: иконка есть у любой
  // задачи; у running — живая консоль (хвост .progress/<stem>.out,
  // обновляется поллингом ленты), у завершённых — финальный результат
  const [outOpen, setOutOpen] = useState(false);
  const outRef = useRef(null);
  // живой вывод: пока пользователь выделяет текст в консоли — его
  // перерисовку и автоскролл замораживаем (frozenOut держит снимок),
  // иначе поллинг каждые 3 с сносит выделение и скопировать нельзя;
  // снял выделение — консоль догоняет до актуального хвоста
  const [frozenOut, setFrozenOut] = useState(null);
  const outNow = useRef(t.output);
  outNow.current = t.output;
  useEffect(() => {
    if (!outOpen) { setFrozenOut(null); return; }
    const h = () => {
      const s = window.getSelection();
      const inOut = s && !s.isCollapsed && outRef.current &&
                    outRef.current.contains(s.anchorNode);
      if (inOut) setFrozenOut(f => f ?? outNow.current);
      else setFrozenOut(null);
    };
    document.addEventListener("selectionchange", h);
    return () => document.removeEventListener("selectionchange", h);
  }, [outOpen]);
  // живая консоль прилипает к низу на каждом обновлении хвоста
  useEffect(() => {
    const el = outRef.current;
    if (outOpen && el && t.status !== "done" && frozenOut === null)
      el.scrollTop = el.scrollHeight;
  }, [t.output, outOpen, frozenOut]);
  const succeeded = t.status === "done" &&
    !(t.task_status && !/exit code: 0/.test(t.task_status));
  // «в работу»: у задачи-вопроса (reply_mode=ask) из модалки 📄 та
  // же карточка уходит в очередь code-задачей — бэк приписывает
  // «реализуй предложение» к промпту, прячет ответ в instr и
  // резюмит ту же сессию темы (новых карточек не создаётся).
  // Кнопка открывает селект code-тем: выбранная колонка забирает
  // карточку и запускает её (move с повышением уровня).
  // Подсвечиваем, когда в ответе Devin есть предложение реализации
  // («если хочешь — сделаем» и т.п.)
  const [workBusy, setWorkBusy] = useState(false);
  const [workMenu, setWorkMenu] = useState(null);
  const offersWork = t.mode === "ask" && succeeded &&
    /если хочешь|могу (сделать|реализовать|добавить|исправить|помочь)|скажи[^\n.]{0,30}сделаю|давай сделаем|готов (сделать|реализовать)|предлагаю|shall i|could implement|can implement/i
      .test(t.output || "");
  const codeCols = (cols || []).filter(c => c.mode === "code");
  const sendToWork = async (key, name) => {
    if (workBusy) return;
    setWorkBusy(true);
    setWorkMenu(null);
    try {
      const d = await (pend || ((_, f) => f()))(t.stem, () =>
        post("/api/task/move", { stem: t.stem, topic: key }));
      if (d.ok) { toast?.(d.started
                    ? "Отправлена в работу — «" + name + "»"
                    : "Перемещена — «" + name + "»");
                  setOutOpen(false); }
      else toast?.("Ошибка: " + (d.error || "?"));
    } catch (e) { toast?.("Сеть: " + e); }
    setWorkBusy(false);
  };
  // «повторить» на упавшей карточке: та же задача новой записью в
  // очередь — промпт/проект/тема/режим/модель/автокоммит сохраняются;
  // retry_of просит бэк стереть старую упавшую запись
  const [retryBusy, setRetryBusy] = useState(false);
  const retry = async () => {
    if (retryBusy) return;
    let text = promptShown || "";
    if (full === null && maybeCut) {
      try {
        const d = await apiJson("/api/task/" + t.stem + "/prompt");
        if (d.ok) { setFull(d.prompt); text = d.prompt; }
      } catch { /* сеть — отправим превью */ }
    }
    if (!text.trim()) return;
    setRetryBusy(true);
    try {
      // пересылаем только опции, которые отличались от дефолта колонки
      // (ov из /api/tasks); у старых записей без ov — как раньше, всё
      const rov = t.ov || { mode: t.mode === "ask", model: !!t.model,
                            ac: t.ac === "0" || t.ac === "1" };
      const body = { text, retry_of: t.stem,
        ...(t.project ? { project: t.project } : {}),
        ...(t.tid ? { topic: String(t.tid) } : {}),
        ...(rov.mode && t.mode ? { mode: t.mode } : {}),
        ...(rov.model && t.model ? { model: t.model } : {}),
        ...(rov.ac && (t.ac === "0" || t.ac === "1")
            ? { auto_commit: t.ac } : {}) };
      const d = await (pend || ((_, f) => f()))(t.stem, () =>
        post("/api/tasks", body));
      if (d.ok) onGone?.(t.stem);   // бэк стёр старую запись (retry_of)
      toast?.(d.ok ? "🔁 Задача поставлена заново — старая удалена"
                  : "Ошибка: " + (d.error || "?"));
    } catch (e) { toast?.("Сеть: " + e); }
    setRetryBusy(false);
  };
  // раскрывать есть что, только если текст задачи обрезан тремя
  // строками — вывод живёт в модалке 📄, «подробнее» его не дублирует
  const txtRef = useRef(null);
  const openRef = useRef(false);
  openRef.current = open;
  const [clamped, setClamped] = useState(false);
  useLayoutEffect(() => {
    const measure = () => {
      // в раскрытом виде текст не клампится — не меряем
      const el = txtRef.current;
      if (el && !openRef.current)
        setClamped(el.scrollHeight > el.clientHeight + 1);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [promptShown]);
  const canExpand = clamped;
  // превью задачи может быть обрезано на 2000 символах — полный текст
  // догружаем при раскрытии
  useEffect(() => {
    if (open && maybeCut) loadFull();
  }, [open]);
  // на мобильной модалки карточки растягиваем почти на всю ширину
  // экрана (узкие отступы), на десктопе — как было
  const dlgMobile = useMediaQuery(t2 => t2.breakpoints.down("md"));
  const dlgSlotProps = dlgMobile
    ? { paper: { sx: { m: 1, width: "calc(100% - 16px)",
                      maxHeight: "calc(100% - 16px)" } } }
    : undefined;
  const st = t.stats || {};
  // стоимость задачи по тарифу модели: каталог /api/models (кэш,
  // без fresh) догружаем при открытии «инфо»; цены парсятся из
  // info.cost_summary вида «$4 / 1M Input · $0.2 / 1M Cached input ·
  // $20 / 1M Output» (sidekick-цены fusion не трогаем — регистр букв)
  const [prices, setPrices] = useState(null);
  useEffect(() => {
    if (info && prices === null)
      apiJson("/api/models").then(d => setPrices(d.models || []))
                            .catch(() => setPrices([]));
  }, [info]);
  const mdl = (prices || []).find(x => x.id === (st.model || t.model));
  const csumm = mdl?.info?.cost_summary || "";
  const price = kind => {
    const m = csumm.match(
      new RegExp(`\\$([\\d.]+)\\s*/\\s*1M\\s+${kind}`));
    return m ? parseFloat(m[1]) : null;
  };
  // prompt_tokens включает закэшированную часть — считаем её по
  // цене cached, остаток по цене input
  const costParts = [
    ["input", Math.max((st.prompt_tokens || 0) -
                       (st.cached_tokens || 0), 0), price("Input")],
    ["кэш", st.cached_tokens || 0, price("Cached input")],
    ["output", st.completion_tokens || 0, price("Output")],
  ].filter(([, , p]) => p != null);
  const hasTok = st.prompt_tokens != null ||
                 st.completion_tokens != null;
  const cost = hasTok && costParts.length
    ? costParts.reduce((s, [, n, p]) => s + n * p / 1e6, 0) : null;
  const freeTier = mdl?.info?.cost_tier === "Free";
  const costStr = freeTier ? "бесплатно"
    : cost != null ? "≈ $" + (cost < 0.01 ? cost.toFixed(4)
                                          : cost.toFixed(2))
    : null;
  const infoRows = [
    ["Статус", t.task_status || null],
    ["Время выполнения", fmtDur(st.duration)],
    ["Модель", st.model || t.model || null],
    ["Стоимость", st.cost != null
      ? "≈ $" + (st.cost < 0.01 ? st.cost.toFixed(4)
                               : st.cost.toFixed(2))
      : costStr],
    ["Токены", st.prompt_tokens != null || st.completion_tokens != null
      ? `prompt ${fmtNum(st.prompt_tokens)}` +
        ` (кэш ${fmtNum(st.cached_tokens)}` +
        (st.prompt_tokens
          ? ` · ${Math.round((st.cached_tokens || 0) /
                             st.prompt_tokens * 100)}%`
          : "") + `)` +
        ` + completion ${fmtNum(st.completion_tokens)}` : null,
      "prompt — весь вход сессии (промпт, история диалога и выводы " +
      "инструментов) на каждом шаге; кэш — часть prompt, которую " +
      "провайдер взял из prefix-кэша (входит в prompt, считается " +
      "дешевле); completion — вывод модели. «Переполнения» кэша " +
      "нет: предел только у окна контекста — при подходе к нему " +
      "сессия компактируется и работа продолжается."],
    ["Шагов сессии", st.steps != null ? fmtNum(st.steps) : null],
    ["Сессия", st.session || null],
  ].filter(([, v]) => v != null && v !== "");
  // «копировать» у статус-чипа — весь текст задачи в буфер обмена;
  // обрезанное превью догружаем перед копированием
  const copyPrompt = async () => {
    let text = promptShown || "";
    if (full === null && maybeCut) {
      try {
        const d = await apiJson("/api/task/" + t.stem + "/prompt");
        if (d.ok) { setFull(d.prompt); text = d.prompt; }
      } catch { /* сеть — копируем что есть */ }
    }
    try {
      await navigator.clipboard.writeText(text);
    } catch { // http/старый браузер — fallback через textarea
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.cssText = "position:fixed;opacity:0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(true);
    toast?.("Текст задачи скопирован");
    setTimeout(() => setCopied(false), 1500);
  };
  // карточка-заметка («сказать», status=note): не уходит Devin, клик
  // по карточке «нажимает» её — композер переходит в режим заметки и
  // дописывает текст в неё. В работу заметка уходит только переносом
  // в колонку уровня «спросить»/«код» (dnd или «переместить»)
  const isNote = t.status === "note";
  // «✨ оформить» — devin переоформляет текст заметки в markdown:
  // результат падает в output (поллинг привезёт) → кнопка «вариант»
  // открывает превью с «применить». Спиннер держим до смены output
  const [fmtBusy, setFmtBusy] = useState(false);
  const fmtBase = useRef("");
  const [fmtOpen, setFmtOpen] = useState(false);
  // t.fmt — серверный флаг «оформление ещё идёт»: спиннер держится и
  // после перезагрузки страницы, пока фоновый прогон не закончит
  const fmtOn = fmtBusy || !!t.fmt;
  useEffect(() => {
    if (fmtBusy && (t.output || "") !== fmtBase.current)
      setFmtBusy(false);
  }, [t.output, fmtBusy]);
  const fmtNote = async () => {
    if (fmtOn) return;
    fmtBase.current = t.output || "";
    setFmtBusy(true);
    try {
      const d = await post("/api/task/format", { stem: t.stem });
      if (!d.ok) {
        toast?.("Ошибка: " + (d.error || "?"));
        setFmtBusy(false);
      }   // ок — ждём, пока поллинг привезёт новый output
    } catch (e) { toast?.("Сеть: " + e); setFmtBusy(false); }
  };
  const fmtApply = async () => {
    try {
      const d = await post("/api/task/apply", { stem: t.stem });
      if (d.ok) { setFmtOpen(false);
                  toast?.("Оформление применено — исходник в «варианте»"); }
      else toast?.("Ошибка: " + (d.error || "?"));
    } catch (e) { toast?.("Сеть: " + e); }
  };
  // инлайн-редактирование заметки: превью подменяется полем
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState("");
  const [editBusy, setEditBusy] = useState(false);
  const startEdit = () => { setEditText(promptShown); setEditing(true); };
  const saveEdit = async () => {
    if (editBusy || !editText.trim()) return;
    setEditBusy(true);
    try {
      const d = await post("/api/task/edit",
                           { stem: t.stem, text: editText });
      if (d.ok) setEditing(false);
      else toast?.("Ошибка: " + (d.error || "?"));
    } catch (e) { toast?.("Сеть: " + e); }
    setEditBusy(false);
  };
  // «переместить»: иконка открывает диалог выбора колонки (на
  // мобильной dnd нет — это основной путь; на десктопе карту тащат
  // за ручку-гриппер). Уровень целевой колонки выше уровня карты →
  // бэк сразу запускает её (заметка→спросить/код, вопрос→код)
  const [moveOpen, setMoveOpen] = useState(false);
  const [moveBusy, setMoveBusy] = useState(false);
  const cardLvl = isNote ? 0 : (t.mode === "ask" ? 1 : 2);
  const curColKey = t.tid ? String(t.tid) : "main";
  const moveTo = async (key, name) => {
    if (moveBusy) return;
    setMoveBusy(true);
    setMoveOpen(false);
    try {
      const d = await (pend || ((_, f) => f()))(t.stem, () =>
        post("/api/task/move", { stem: t.stem, topic: key }));
      if (d.ok) {
        setMoveOpen(false);
        toast?.(d.started ? "▶ Запущена в «" + name + "»"
                         : "Перемещена в «" + name + "»");
        if (isNote && sel) onNote?.(t);  // ушла в работу — отжать
      } else toast?.("Ошибка: " + (d.error || "?"));
    } catch (e) { toast?.("Сеть: " + e); }
    setMoveBusy(false);
  };
  // мелкие мета-чипы шапки: один стиль, воздух вокруг текста
  const metaSx = { height: 22, fontSize: 11, fontWeight: 500,
                   borderRadius: "7px",
                   "& .MuiChip-label": { px: "8px" } };
  // чипы настроек — только когда значение отличается от дефолта
  // колонки (ov из /api/tasks); у старых записей без ov — показываем
  const ov = t.ov || { mode: true, model: true, ac: true };
  return (
    <Card elevation={0} data-stem={t.stem}
      onClick={isNote ? () => onNote?.(t) : undefined}
      onDragOver={isNote ? e => onMergeOver?.(e, t) : undefined}
      onDrop={isNote ? e => onMergeDrop?.(e, t) : undefined}
      onDragLeave={isNote ? () => onMergeLeave?.(t) : undefined}
      sx={{
      mb: 1.6, borderRadius: "14px", position: "relative",
      border: "1px solid", borderColor: "divider",
      cursor: isNote ? "pointer" : "default",
      transition: "box-shadow .2s ease, border-color .2s ease",
      ...(sel && { borderColor: "#5e6ad2",
                   bgcolor: "rgba(94,106,210,.05)",
                   boxShadow: "0 0 0 1px #5e6ad2" }),
      ...(mergeSel && { borderColor: "#5e6ad2",
                        borderStyle: "dashed",
                        bgcolor: "rgba(94,106,210,.07)",
                        boxShadow: "0 0 0 2px rgba(94,106,210,.35)" }),
      "&:hover": { borderColor: sel ? "#5e6ad2" : "#c9cfda",
                   boxShadow: sel ? "0 0 0 1px #5e6ad2"
                                  : "0 4px 18px rgba(16,24,40,.07)" } }}>
      {(pending || moveBusy || workBusy || retryBusy) && <PendOverlay />}
      <CardContent sx={{ p: "14px 20px 10px",
                         "&:last-child": { pb: "10px" } }}>
        <Box sx={{ display: "flex", justifyContent: "space-between",
                   alignItems: "flex-start", gap: 1.5,
                   flexWrap: "wrap", mb: 1.2 }}>
          <Box sx={{ display: "flex", alignItems: "center",
                     gap: 0.8, flexWrap: "wrap", minWidth: 0 }}>
            {/* ручка dnd (только десктоп): тащим карту между
                колонками — место вставки подсвечивается пунктирным
                плейсхолдером; на мобильной вместо этого — иконка
                «переместить» с диалогом */}
            {!dlgMobile && (
              <Tooltip title="перетащить в другую колонку или на другое место">
                <Box component="span" draggable
                     onDragStart={e => {
                       e.dataTransfer.setData("text/plain", t.stem);
                       e.dataTransfer.effectAllowed = "move";
                       dragStemNow = { stem: t.stem, note: isNote }; }}
                     onClick={e => e.stopPropagation()}
                     sx={{ cursor: "grab", display: "inline-flex",
                           mr: -0.3, color: "text.disabled",
                           "&:hover": { color: "text.secondary" },
                           "&:active": { cursor: "grabbing" } }}>
                  <DragIndicatorIcon sx={{ fontSize: 15 }} />
                </Box>
              </Tooltip>)}
            <Typography variant="caption" color="text.secondary"
                        sx={{ fontSize: 12, mr: 0.2 }}>
              {new Date(t.created * 1000).toLocaleString("ru-RU")}
              <Elapsed started={t.started} finished={t.finished} />
            </Typography>
            <Tooltip title="откуда поставлена задача">
              <Chip size="small" variant="outlined" sx={metaSx}
                    label={SRC_RU[t.source] || t.source || ""} />
            </Tooltip>
            {ov.model && t.model &&
              <Tooltip title="модель задачи — отличается от дефолта колонки">
                <Chip size="small" variant="outlined" sx={metaSx}
                      label={t.model} />
              </Tooltip>}
            {ov.mode &&
            <Tooltip title={(t.mode === "ask"
              ? "режим «вопрос» — только чтение"
              : t.mode === "say"
              ? "карточка-заметка — не уходит Devin"
              : "режим «код» — полный доступ") +
              " — отличается от дефолта колонки"}>
              <Chip size="small" variant="outlined" sx={metaSx}
                    label={t.mode === "ask" ? "💬 вопрос"
                           : t.mode === "say" ? "📝 заметка"
                           : "🛠 код"} />
            </Tooltip>}
            {ov.ac &&
            <Tooltip title={(t.ac === "1"
              ? "автокоммит и пуш после задачи"
              : "изменения не коммитятся автоматически") +
              " — отличается от дефолта колонки"}>
              <Chip size="small" variant="outlined"
                    sx={{ ...metaSx,
                          color: t.ac === "1" ? "#2e7d32" : undefined,
                          borderColor: t.ac === "1" ? "#a5d6a7"
                                                  : undefined }}
                    label={t.ac === "1" ? "⚡ автокоммит"
                                        : "✋ коммит вручную"} />
            </Tooltip>}
            {t.topic && !hideTopic &&
              <Tooltip title="тема задачи">
                <Chip size="small" variant="outlined" sx={metaSx}
                      label={"🧵 " + t.topic} />
              </Tooltip>}
            {t.tag &&
              <Tooltip title="тег задачи — версия/прогресс от воркера">
                <Chip size="small" color="primary"
                      sx={{ ...metaSx,
                            bgcolor: "#eceefc", color: "#4c57b8" }}
                      label={t.tag} />
              </Tooltip>}
          </Box>
          <Box onClick={e => e.stopPropagation()}
               sx={{ display: "flex", alignItems: "center",
                     gap: 0.8, flexShrink: 0 }}>
            {t.status === "running" && onStop && (
              <Tooltip title="остановить выполнение задачи">
                <Button size="small" variant="outlined" color="error"
                        onClick={() => onStop(t)}
                        sx={{ fontSize: 11, px: 1.2, height: 26,
                              borderRadius: "7px", whiteSpace: "nowrap",
                              textTransform: "none" }}>
                  ⛔ стоп
                </Button>
              </Tooltip>
            )}
            {t.status === "queued" && onCancel && (
              <Tooltip title="убрать задачу из очереди">
                <Button size="small" variant="outlined" color="error"
                        onClick={() => onCancel(t)}
                        sx={{ fontSize: 11, px: 1.2, height: 26,
                              borderRadius: "7px", whiteSpace: "nowrap",
                              textTransform: "none" }}>
                  ✖ удалить
                </Button>
              </Tooltip>
            )}
            <Tooltip title={isNote ? "текст заметки"
                          : succeeded ? "результат задачи"
                                      : "вывод задачи"}>
              <IconButton size="small" onClick={() => setOutOpen(true)}
                sx={{ p: "3px", color: "text.secondary" }}>
                <ForumOutlinedIcon sx={{ fontSize: 15 }} />
              </IconButton>
            </Tooltip>
            {t.status === "done" && (
              <Tooltip title="статистика задачи">
                <IconButton size="small" onClick={() => setInfo(true)}
                  sx={{ p: "3px", color: "text.secondary" }}>
                  <InfoOutlinedIcon sx={{ fontSize: 15 }} />
                </IconButton>
              </Tooltip>
            )}
            {t.status === "done" && onCont && (
              <Tooltip title="продолжить задачу — дописать доделку, карточка уйдёт в работу той же сессией">
                <IconButton size="small" onClick={() => onCont(t)}
                  sx={{ p: "3px", color: sel ? "primary.main"
                                           : "text.secondary" }}>
                  <RedoIcon sx={{ fontSize: 15 }} />
                </IconButton>
              </Tooltip>
            )}
            {t.status === "done" && !succeeded && (
              <Tooltip title="повторить задачу — в очередь с теми же параметрами, старая запись удалится">
                <IconButton size="small" onClick={retry}
                  disabled={retryBusy}
                  sx={{ p: "3px", color: "text.secondary" }}>
                  <ReplayIcon sx={{ fontSize: 15 }} />
                </IconButton>
              </Tooltip>
            )}
            {(isNote || t.status === "done") && onDel && (
              <Tooltip title={isNote ? "удалить заметку"
                                     : "удалить задачу"}>
                <IconButton size="small" onClick={() => onDel(t)}
                  sx={{ p: "3px", color: "error.main" }}>
                  <DeleteOutlinedIcon sx={{ fontSize: 15 }} />
                </IconButton>
              </Tooltip>
            )}
            <Tooltip title="скопировать текст задачи">
              <IconButton size="small" onClick={copyPrompt}
                sx={{ p: "3px", color: copied ? "#2e7d32"
                                            : "text.secondary" }}>
                {copied ? <CheckIcon sx={{ fontSize: 15 }} />
                        : <ContentCopyIcon sx={{ fontSize: 15 }} />}
              </IconButton>
            </Tooltip>
            {(cols || []).some(c => c.key !== curColKey) && (
              <Tooltip title="переместить в другую тему — уровень колонки выше запустит карточку">
                <IconButton size="small"
                  onClick={() => setMoveOpen(true)}
                  sx={{ p: "3px", color: "text.secondary" }}>
                  <DriveFileMoveIcon sx={{ fontSize: 15 }} />
                </IconButton>
              </Tooltip>
            )}
            {isNote && !editing && onDict && (
              <Tooltip title={dictOn ? "стоп запись"
                                     : "надиктовать текст в заметку"}>
                <IconButton size="small"
                  onClick={e => { e.stopPropagation(); onDict(t); }}
                  sx={{ p: "3px",
                        color: dictOn || sel ? "error.main"
                                             : "text.secondary" }}>
                  {dictOn ? <StopIcon sx={{ fontSize: 15 }} />
                          : <MicIcon sx={{ fontSize: 15 }} />}
                </IconButton>
              </Tooltip>
            )}
            {isNote && !editing && (
              <Tooltip title="редактировать текст заметки">
                <IconButton size="small"
                  onClick={e => { e.stopPropagation(); startEdit(); }}
                  sx={{ p: "3px", color: "text.secondary" }}>
                  <EditOutlinedIcon sx={{ fontSize: 15 }} />
                </IconButton>
              </Tooltip>
            )}
            {isNote && (
              <Tooltip title="оформить текст в markdown через Devin — результат появится кнопкой «✨ вариант»">
                <IconButton size="small" disabled={fmtOn}
                  onClick={e => { e.stopPropagation(); fmtNote(); }}
                  sx={{ p: "3px", color: "text.secondary" }}>
                  {fmtOn
                    ? <Box component="span" sx={{
                        display: "inline-block",
                        width: 13, height: 13, borderRadius: "50%",
                        border: "2px solid #5e6ad2",
                        borderTopColor: "transparent",
                        animation: "rot .8s linear infinite",
                        "@keyframes rot":
                          { to: { transform: "rotate(360deg)" } } }} />
                    : <AutoAwesomeIcon sx={{ fontSize: 15 }} />}
                </IconButton>
              </Tooltip>
            )}
          </Box>
          {/* действия заметки — отдельный flex-ребёнок внешнего
              wrap-ряда: не влезает в ширину — группа уходит на новую
              строку, внутри себя тоже переносится */}
          {isNote
            ? !!t.output && (
              <Box sx={{ display: "flex", alignItems: "center",
                         gap: 0.8, flexWrap: "wrap" }}>
                <Button size="small" variant="outlined"
                  onClick={e => { e.stopPropagation();
                                  setFmtOpen(true); }}
                  sx={{ fontSize: 11, px: 1, height: 26,
                        borderRadius: "7px", whiteSpace: "nowrap",
                        textTransform: "none" }}>
                  ✨ вариант
                </Button>
              </Box>)
            : <StatusChip t={t} />}
        </Box>
        {isNote ? (
          editing ? (
            <Box onClick={e => e.stopPropagation()}>
              <TextField multiline fullWidth autoFocus size="small"
                minRows={3} maxRows={16}
                value={editText}
                onChange={e => setEditText(e.target.value)}
                onKeyDown={e => {
                  if (e.key === "Escape") setEditing(false);
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey))
                    saveEdit(); }}
                sx={{ "& .MuiInputBase-root":
                      { fontSize: 13.5, lineHeight: 1.62 } }} />
              <Box sx={{ display: "flex", gap: 0.8, mt: 0.8 }}>
                <Button size="small" variant="contained"
                  onClick={saveEdit} disabled={editBusy}
                  sx={{ fontSize: 11, px: 1.2, height: 26,
                        borderRadius: "7px", textTransform: "none" }}>
                  {editBusy ? "сохраняю…" : "Сохранить"}
                </Button>
                <Button size="small" variant="outlined"
                  onClick={() => setEditing(false)}
                  sx={{ fontSize: 11, px: 1.2, height: 26,
                        borderRadius: "7px", textTransform: "none" }}>
                  Отмена
                </Button>
              </Box>
            </Box>
          ) : (
          <Box ref={txtRef}
            sx={{ fontSize: 13.5, lineHeight: 1.62,
                  overflowWrap: "anywhere", overflowX: "hidden",
                  ...(open ? {} : { maxHeight: 76,
                                    overflow: "hidden" }) }}>
            <Markdown text={promptShown} />
          </Box>
          )
        ) : (
        <Typography variant="body2" ref={txtRef}
          onClick={(canExpand || open)
                   ? () => setOpen(o => !o) : undefined}
          sx={{ whiteSpace: "pre-wrap", fontWeight: 500, fontSize: 13.5,
                lineHeight: 1.62,
                cursor: (canExpand || open) ? "pointer" : "inherit",
                ...(!open && {
                  display: "-webkit-box", WebkitBoxOrient: "vertical",
                  WebkitLineClamp: 3, overflow: "hidden" }) }}>
          {promptShown}</Typography>)}
        {maybeCut && (
          <Typography variant="caption"
            onClick={e => { e.stopPropagation(); loadFull(); }}
            sx={{ display: "inline-block", mt: 0.5,
                  color: "#5e6ad2", cursor: "pointer", fontWeight: 500,
                  "&:hover": { textDecoration: "underline" } }}>
            … показать весь текст задачи
          </Typography>)}
        {canExpand && (
        <Box onClick={e => { e.stopPropagation(); setOpen(o => !o); }}
             sx={{ display: "flex", alignItems: "center", gap: 0.4,
                   justifyContent: "center", cursor: "pointer", mt: 1.2,
                   py: 0.3, borderRadius: "8px",
                   color: "text.secondary", fontSize: 11.5,
                   transition: "color .15s, background .15s",
                   "&:hover": { color: "#5e6ad2",
                                bgcolor: "rgba(94,106,210,.07)" } }}>
          {open ? "свернуть" : "подробнее"}
          <ExpandMoreIcon sx={{
            fontSize: 16, transition: "transform .25s",
            transform: open ? "rotate(180deg)" : "none" }} />
        </Box>)}
        <Dialog open={info} onClose={() => setInfo(false)}
                maxWidth="xs" fullWidth slotProps={dlgSlotProps}>
          <DialogTitle sx={{ fontSize: 15, fontWeight: 600, pr: 6 }}>
            Статистика задачи
            <Tooltip title="закрыть">
              <IconButton size="small" onClick={() => setInfo(false)}
                sx={{ position: "absolute", right: 12, top: 10,
                      color: "text.secondary" }}>
                <CloseIcon sx={{ fontSize: 18 }} />
              </IconButton>
            </Tooltip>
          </DialogTitle>
          <DialogContent sx={{ pb: 2.5 }}>
            <Box>
              {infoRows.map(([k, v, hint]) => (
                <Box key={k} sx={{ display: "flex",
                                  justifyContent: "space-between",
                                  gap: 2, py: 0.7,
                                  borderBottom: "1px solid",
                                  borderColor: "divider" }}>
                  <Typography variant="body2" color="text.secondary"
                              sx={{ fontSize: 13, flexShrink: 0 }}>
                    {hint
                      ? <Tooltip title={hint} placement="top-start">
                          <Box component="span"
                               sx={{ borderBottom: "1px dotted",
                                     borderColor: "text.secondary",
                                     cursor: "help" }}>{k}</Box>
                        </Tooltip>
                      : k}</Typography>
                  <Typography variant="body2"
                              sx={{ fontSize: 12.5, fontFamily: MONO,
                                    textAlign: "right",
                                    wordBreak: "break-all" }}>
                    {v}</Typography>
                </Box>
              ))}
            </Box>
            {cost != null && (
              <Typography variant="caption" color="text.secondary"
                          sx={{ display: "block", mt: 1, fontSize: 11,
                                wordBreak: "break-word" }}>
                {costParts.map(([k, n, p]) =>
                  `${k} ${fmtNum(n)} × $${p}/1M`).join(" + ")}
                {csumm ? ` · тариф: ${csumm}` : ""}
              </Typography>)}
            {freeTier && (
              <Typography variant="caption" color="text.secondary"
                          sx={{ display: "block", mt: 1, fontSize: 11 }}>
                модель бесплатная — тариф Free
              </Typography>)}
            {hasTok && prices !== null && cost == null && !freeTier && (
              <Typography variant="caption" color="text.secondary"
                          sx={{ display: "block", mt: 1, fontSize: 11 }}>
                тариф модели неизвестен — стоимость не посчитана
              </Typography>)}
            {st.prompt_tokens == null && st.completion_tokens == null && (
              <Typography variant="caption" color="text.secondary"
                          sx={{ display: "block", mt: 1.2 }}>
                детальные метрики сессии не собраны (задача до
                появления статистики или export-файл недоступен)
              </Typography>)}
          </DialogContent>
        </Dialog>
        <Dialog open={fmtOpen} onClose={() => setFmtOpen(false)}
                maxWidth="md" fullWidth slotProps={dlgSlotProps}>
          <DialogTitle sx={{ fontSize: 15, fontWeight: 600, pr: 6 }}>
            ✨ Оформленный вариант заметки
            <Tooltip title="закрыть">
              <IconButton size="small" onClick={() => setFmtOpen(false)}
                sx={{ position: "absolute", right: 12, top: 10,
                      color: "text.secondary" }}>
                <CloseIcon sx={{ fontSize: 18 }} />
              </IconButton>
            </Tooltip>
          </DialogTitle>
          <DialogContent dividers
                         sx={{ "& .md": { maxHeight: "none" } }}>
            <Markdown text={t.output || ""} />
          </DialogContent>
          <DialogActions>
            <Button size="small" onClick={() => setFmtOpen(false)}
                    sx={{ textTransform: "none" }}>
              Отмена
            </Button>
            <Button size="small" variant="contained" onClick={fmtApply}
                    sx={{ textTransform: "none" }}>
              Применить — заменить текст (исходник вернётся в «вариант»)
            </Button>
          </DialogActions>
        </Dialog>
        <Dialog open={outOpen} onClose={() => setOutOpen(false)}
                maxWidth="md" fullWidth slotProps={dlgSlotProps}>
          <DialogTitle sx={{ fontSize: 15, fontWeight: 600, pr: 6 }}>
            {isNote ? "Заметка"
                   : succeeded ? "Результат задачи" : "Вывод задачи"}
            {frozenOut !== null &&
              <Tooltip title="выделен текст — обновление вывода на паузе, снимите выделение для продолжения">
                <Chip size="small" variant="outlined"
                      label="⏸ пауза"
                      sx={{ ml: 1, height: 17, fontSize: 9.5,
                            borderRadius: "6px" }} />
              </Tooltip>}
            {t.mode === "ask" && t.status === "done" && (<>
              <Tooltip title="в работу той же карточкой — выбрать code-тему">
                <span>
                  <Button size="small"
                          variant={offersWork ? "contained" : "outlined"}
                          onClick={e => setWorkMenu(e.currentTarget)}
                          disabled={workBusy}
                          sx={{ ml: 1.2, fontSize: 11.5, px: 1.2, py: 0.1,
                                textTransform: "none",
                                whiteSpace: "nowrap" }}>
                    {workBusy ? "отправляю…" : "▶ в работу"}
                  </Button>
                </span>
              </Tooltip>
              <Menu anchorEl={workMenu} open={!!workMenu}
                    onClose={() => setWorkMenu(null)}>
                {codeCols.length
                  ? codeCols.map(c => (
                    <MenuItem key={c.key} dense sx={{ fontSize: 13 }}
                      onClick={() => { setWorkMenu(null);
                                       sendToWork(c.key, c.name); }}>
                      🛠 {c.name}
                    </MenuItem>))
                  : <MenuItem dense disabled sx={{ fontSize: 13 }}>
                      нет темы с режимом «код»
                    </MenuItem>}
              </Menu>
            </>)}
            <Tooltip title="закрыть">
              <IconButton size="small" onClick={() => setOutOpen(false)}
                sx={{ position: "absolute", right: 12, top: 10,
                      color: "text.secondary" }}>
                <CloseIcon sx={{ fontSize: 18 }} />
              </IconButton>
            </Tooltip>
          </DialogTitle>
          <DialogContent dividers
                         sx={{ "& .md": { maxHeight: "none" } }}>
            <Box>
              {isNote
                ? <Markdown text={promptShown} />
                : t.status === "done"
                ? (t.output
                    ? <Markdown text={t.output} />
                    : <Typography variant="body2" color="text.secondary">
                        вывод пуст — Devin ничего не вернул</Typography>)
                : ((frozenOut ?? t.output)
                    ? <pre className="out" ref={outRef}
                           style={{ maxHeight: "60vh" }}>
                        {frozenOut ?? t.output}</pre>
                    : <Typography variant="body2" color="text.secondary">
                        {t.status === "queued"
                          ? "в очереди — вывод ещё пуст"
                          : "вывод пока пуст"}</Typography>)}
            </Box>
          </DialogContent>
        </Dialog>
        {/* «переместить» — выбор целевой колонки; у неё подписан
            уровень и станет ли перенос запуском (уровни: заметка <
            спросить < код — повышение уровня стартует карточку) */}
        <Dialog open={moveOpen} onClose={() => setMoveOpen(false)}
                maxWidth="xs" fullWidth slotProps={dlgSlotProps}>
          <DialogTitle sx={{ fontSize: 15, fontWeight: 600, pr: 6 }}>
            Переместить карточку
            <Tooltip title="закрыть">
              <IconButton size="small" onClick={() => setMoveOpen(false)}
                sx={{ position: "absolute", right: 12, top: 10,
                      color: "text.secondary" }}>
                <CloseIcon sx={{ fontSize: 18 }} />
              </IconButton>
            </Tooltip>
          </DialogTitle>
          <DialogContent dividers sx={{ p: 0 }}>
            {(cols || []).filter(c => c.key !== curColKey).map(c => {
              const lvl = c.mode === "say" ? 0
                                   : c.mode === "ask" ? 1 : 2;
              const up = lvl > cardLvl;
              return (
                <ListItemButton key={c.key} dense disabled={moveBusy}
                  onClick={() => moveTo(c.key, c.name)}
                  sx={{ px: 2, py: 0.9 }}>
                  <Typography noWrap
                              sx={{ flex: 1, minWidth: 0,
                                    fontSize: 13, fontWeight: 500 }}>
                    {c.name}</Typography>
                  <Chip size="small" variant="outlined"
                        label={c.mode === "say" ? "📝 заметка"
                               : c.mode === "ask" ? "💬 спросить"
                                                  : "🛠 код"}
                        sx={{ height: 17, fontSize: 9.5, flexShrink: 0,
                              borderRadius: "6px" }} />
                  <Typography variant="caption"
                        color={up ? "primary" : "text.secondary"}
                        sx={{ ml: 1, fontSize: 11, flexShrink: 0,
                              fontWeight: up ? 600 : 400 }}>
                    {up ? "запустится" : "просто перенос"}
                  </Typography>
                </ListItemButton>);
            })}
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
});

// Project picker in the header — replaces the old tabs row; selection
// persists server-side via POST /api/project (kv.project_web).
// вкладки проектов — отдельная полоса под шапкой, перед доской:
// вкладка = открытый проект (крестик закрывает), «+» — список
// всех проектов → новая вкладка; переключение — перезагрузкой
// страницы (проект/цвет/иконка подтягиваются целиком)
function ProjectTabs({ projects, tabs, current, onTab, onClose, onAdd,
                       wsmap, wsList, onWs, onSettings, accent }) {
  const [menu, setMenu] = useState(null);
  const [wsMenu, setWsMenu] = useState(null);
  const wsColor = p => {
    const w = (wsList || []).find(w => w.id === (wsmap || {})[p]);
    return w ? w.color : "#999";
  };
  const acc = accent || "#5e6ad2";
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 0.5,
               overflowX: "auto", flexShrink: 0,
               px: { xs: 0.6, md: 1.2 }, pt: 0.5,
               bgcolor: "background.paper",
               borderBottom: "1px solid", borderColor: "divider",
               "&::-webkit-scrollbar": { height: 4 } }}>
      {tabs.map(p => (
        <Box key={p} onClick={() => onTab(p)}
             sx={{ display: "flex", alignItems: "center", gap: 0.4,
                   height: 30, px: 1.1, flexShrink: 0,
                   borderRadius: "8px 8px 0 0", fontSize: 13,
                   cursor: "pointer", userSelect: "none",
                   bgcolor: p === current ? acc
                                          : "rgba(28,33,40,.05)",
                   color: p === current ? "#fff" : "text.secondary",
                   fontWeight: p === current ? 600 : 400,
                   "&:hover": { bgcolor: p === current
                     ? acc : "rgba(28,33,40,.09)" } }}>
          <WsDot color={wsColor(p)} />
          <Typography component="span" noWrap
                      sx={{ fontSize: "inherit", maxWidth: 160 }}>
            {p}
          </Typography>
          <IconButton size="small"
            onClick={e => { e.stopPropagation(); onClose(p); }}
            sx={{ p: 0.1, color: "inherit", opacity: .65,
                  "&:hover": { opacity: 1 } }}>
            <CloseIcon sx={{ fontSize: 13 }} />
          </IconButton>
        </Box>))}
      <Tooltip title="открыть проект в новой вкладке">
        <IconButton size="small" onClick={e => setMenu(e.currentTarget)}
                    sx={{ color: acc, borderRadius: "8px",
                          width: 26, height: 26, flexShrink: 0,
                          "&:hover": { bgcolor: "rgba(28,33,40,.07)" } }}>
          <AddIcon sx={{ fontSize: 19 }} />
        </IconButton>
      </Tooltip>
      <Menu anchorEl={menu} open={!!menu} onClose={() => setMenu(null)}>
        {(() => { let lastWid = -1;
          return projects.map(p => {
            const wid = (wsmap || {})[p];
            const hdr = wid !== lastWid
              ? (lastWid = wid,
                 <ListSubheader key={"wsh" + wid}
                   sx={{ lineHeight: "28px" }}>
                   {((wsList || []).find(w => w.id === wid) || {}).name
                    || "без пространства"}
                 </ListSubheader>)
              : null;
            return [hdr,
              <MenuItem key={p} sx={{ fontSize: 13, display: "flex",
                                      alignItems: "center" }}
                        onClick={() => { setMenu(null); onTab(p); }}>
                <WsDot color={wsColor(p)} />
                <Box sx={{ flex: 1 }}>{p}</Box>
                <IconButton size="small" sx={{ p: 0.2, ml: 1 }}
                  onClick={e => { e.stopPropagation();
                                  setWsMenu({ a: e.currentTarget, p }); }}>
                  <WorkspacesIcon sx={{ fontSize: 15 }} />
                </IconButton>
                <IconButton size="small" sx={{ p: 0.2 }}
                  onClick={e => { e.stopPropagation(); onSettings?.(p); }}>
                  <TuneIcon sx={{ fontSize: 15 }} />
                </IconButton>
              </MenuItem>];
          }); })()}
        <MenuItem sx={{ color: "#5e6ad2", fontSize: 13 }}
                  onClick={() => { setMenu(null); onAdd?.(); }}>
          ➕ Добавить проект…
        </MenuItem>
      </Menu>
      <Menu anchorEl={wsMenu?.a} open={!!wsMenu}
            onClose={() => setWsMenu(null)}>
        {(wsList || []).map(w => (
          <MenuItem key={w.id}
            onClick={() => { onWs(wsMenu.p, w.id); setWsMenu(null); }}>
            <WsDot color={w.color} />{w.name}
          </MenuItem>))}
      </Menu>
    </Box>);
}

// статистика темы (topic_stats): таблица «задача от <дата> · модель ·
// токены · цена» + итоги; история живёт отдельно от карточек —
// удаление задачи её не трогает. «Очистить историю» стирает
// только записи статистики (инлайн-подтверждение)
function TopicStatsDlg({ dlg, project, onClose, toast }) {
  const [data, setData] = useState(null);   // {rows,total}|"err"
  const [sure, setSure] = useState(false);
  const [busy, setBusy] = useState(false);
  const key = dlg?.key;
  useEffect(() => {
    setSure(false);
    if (!key) return;
    setData(null);
    apiJson("/api/topic/stats?project=" + encodeURIComponent(project)
            + "&topic=" + encodeURIComponent(key))
      .then(d => setData(d.ok ? d : "err"))
      .catch(() => setData("err"));
  }, [key, project]);
  const clear = async () => {
    setBusy(true);
    const d = await post("/api/topic/stats/clear",
                         { project, topic: key }).catch(() => null);
    setBusy(false); setSure(false);
    if (d?.ok) { setData({ rows: [], total: {} });
                 toast?.("История очищена"); }
    else toast?.("Ошибка: " + (d?.error || "сеть"));
  };
  const fmtDate = ts => new Date(ts * 1000)
    .toLocaleString("ru-RU", { day: "2-digit", month: "2-digit",
                               hour: "2-digit", minute: "2-digit" });
  const money = c => c == null ? "—"
    : "$" + (c < 0.01 ? c.toFixed(4) : c.toFixed(2));
  const rows = data && data !== "err" ? data.rows : [];
  const tot = (data && data !== "err" && data.total) || {};
  return (
    <Dialog open={!!dlg} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ fontSize: 16, py: 1.2,
                         display: "flex", alignItems: "center" }}>
        📊 Статистика — {dlg?.name}
        <Box sx={{ flex: 1 }} />
        <IconButton size="small" onClick={onClose}>
          <CloseIcon sx={{ fontSize: 18 }} />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers sx={{ p: 1 }}>
        {data === null &&
          <Typography sx={{ p: 2, fontSize: 13 }}
                      color="text.secondary">Загружаю…</Typography>}
        {data === "err" &&
          <Typography sx={{ p: 2, fontSize: 13 }}
                      color="error">Не удалось загрузить</Typography>}
        {rows.map(r => (
          <Box key={r.id} sx={{ display: "flex", gap: 1, py: 0.4,
                 fontSize: 12.5, flexWrap: "wrap",
                 borderBottom: "1px solid", borderColor: "divider" }}>
            <Typography component="span"
              sx={{ fontSize: "inherit", minWidth: 130 }}>
              задача от {fmtDate(r.created)}
            </Typography>
            <Typography component="span"
              sx={{ fontSize: "inherit", color: "text.secondary",
                    flex: 1, minWidth: 90 }}>
              {r.model || "—"}
            </Typography>
            <Typography component="span"
              sx={{ fontSize: "inherit",
                    fontFamily: "ui-monospace, Menlo, monospace",
                    color: "text.secondary" }}>
              {fmtNum(r.prompt_tok)}·кэш {fmtNum(r.cached_tok)}
              ·out {fmtNum(r.completion_tok)}
            </Typography>
            <Tooltip title="время выполнения — от старта Devin до готовности, очередь не считается">
              <Typography component="span"
                sx={{ fontSize: "inherit",
                      fontFamily: "ui-monospace, Menlo, monospace",
                      color: r.duration ? "text.primary"
                                        : "text.disabled",
                      minWidth: 52, textAlign: "right" }}>
                {r.duration ? fmtDur(r.duration) : "—"}
              </Typography>
            </Tooltip>
            <Typography component="span"
              sx={{ fontSize: "inherit", fontWeight: 600,
                    minWidth: 56, textAlign: "right" }}>
              {money(r.cost)}
            </Typography>
          </Box>))}
        {data && data !== "err" && !rows.length &&
          <Typography sx={{ p: 2, fontSize: 13 }}
                      color="text.secondary">пока нет записей</Typography>}
      </DialogContent>
      <DialogActions sx={{ px: 2, py: 1, display: "flex",
                           alignItems: "center", gap: 1 }}>
        <Typography variant="body2" sx={{ fontSize: 12.5 }}>
          итого: задач {tot.tasks || 0} · prompt {fmtNum(tot.prompt)}
          (кэш {fmtNum(tot.cached)}) + out {fmtNum(tot.completion)}
          {!!tot.duration && " · ⏱ " + fmtDur(tot.duration)}
          {" · ≈ " + money(tot.cost || 0)}
        </Typography>
        <Box sx={{ flex: 1 }} />
        {sure ? (<>
          <Button size="small" color="error" variant="contained"
            onClick={clear} disabled={busy}
            sx={{ textTransform: "none", fontSize: 12 }}>
            {busy ? "чищу…" : "Да, очистить"}</Button>
          <Button size="small" onClick={() => setSure(false)}
            sx={{ textTransform: "none", fontSize: 12 }}>Нет</Button>
        </>) : (
          <Button size="small" color="error" variant="outlined"
            onClick={() => setSure(true)} disabled={!rows.length}
            sx={{ textTransform: "none", fontSize: 12 }}>
            Очистить историю</Button>)}
      </DialogActions>
    </Dialog>);
}

function ProjectSelect({ projects, current, onChange, onAdd,
                         wsmap, wsList, onWs, onSettings }) {
  const [wsMenu, setWsMenu] = useState(null); // {anchor, project}
  const wsColor = p => {
    const w = (wsList || []).find(w => w.id === (wsmap || {})[p]);
    return w ? w.color : "#999";
  };
  let lastWid = -1;
  return (<>
    <Select size="small" value={current || ""} displayEmpty
            renderValue={v => v || ""}
            onChange={e => e.target.value === "__add__"
                      ? onAdd?.() : onChange(e.target.value)}
            sx={{ color: "#fff", height: 32, fontSize: 13, maxWidth: 200,
                  bgcolor: "rgba(255,255,255,.15)", borderRadius: "10px",
                  "& .MuiSelect-icon": { color: "rgba(255,255,255,.8)" },
                  "& .MuiOutlinedInput-notchedOutline":
                    { borderColor: "rgba(255,255,255,.28)" },
                  "&:hover .MuiOutlinedInput-notchedOutline":
                    { borderColor: "rgba(255,255,255,.45)" } }}>
      {projects.map(p => {
        const wid = (wsmap || {})[p];
        const hdr = wid !== lastWid
          ? (lastWid = wid,
             <ListSubheader key={"wsh" + wid} sx={{ lineHeight: "28px" }}>
               {((wsList || []).find(w => w.id === wid) || {}).name ||
                "без пространства"}
             </ListSubheader>)
          : null;
        return [
          hdr,
        <MenuItem key={p} value={p}
                  sx={{ display: "flex", alignItems: "center" }}>
          <WsDot color={wsColor(p)} />
          <Box sx={{ flex: 1 }}>{p}</Box>
          <Tooltip title="перенести в пространство">
            <IconButton size="small"
              onClick={e => { e.stopPropagation();
                              setWsMenu({ a: e.currentTarget, p }); }}
              sx={{ p: 0.2, ml: 1 }}>
              <WorkspacesIcon sx={{ fontSize: 15 }} />
            </IconButton>
          </Tooltip>
          <Tooltip title="настройки проекта">
            <IconButton size="small"
              onClick={e => { e.stopPropagation(); onSettings?.(p); }}
              sx={{ p: 0.2 }}>
              <TuneIcon sx={{ fontSize: 15 }} />
            </IconButton>
          </Tooltip>
        </MenuItem>];
      })}
      <MenuItem value="__add__" sx={{ color: "#5e6ad2", fontSize: 13 }}>
        ➕ Добавить проект…
      </MenuItem>
    </Select>
    <Menu anchorEl={wsMenu?.a} open={!!wsMenu}
          onClose={() => setWsMenu(null)}>
      {(wsList || []).map(w => (
        <MenuItem key={w.id}
          onClick={() => { onWs(wsMenu.p, w.id); setWsMenu(null); }}>
          <WsDot color={w.color} />{w.name}
        </MenuItem>))}
    </Menu>
  </>);
}

function ModelSelect({ models, current, onChange, sx }) {
  return (
    <Select size="small" value={current || ""} onChange={e => onChange(e.target.value)}
            displayEmpty sx={{ color: "#fff", maxWidth: 320, height: 32,
              bgcolor: "rgba(255,255,255,.15)", fontSize: 13,
              borderRadius: "10px",
              "& .MuiOutlinedInput-notchedOutline":
                { borderColor: "rgba(255,255,255,.28)" }, ...sx }}>
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
              bgcolor: "rgba(255,255,255,.15)", fontSize: 13,
              borderRadius: "10px",
              "& .MuiOutlinedInput-notchedOutline":
                { borderColor: "rgba(255,255,255,.28)" }, ...sx }}>
      <MenuItem value="code">🛠 код</MenuItem>
      <MenuItem value="ask">💬 вопрос</MenuItem>
    </Select>
  );
}

// Секция боковой панели — единый раскрывающийся список (шеврон + заголовок
// + чип/действия справа). Раскрытие хранится в настройках юзера+проекта
// (us:<uid>.panel:<проект> через /api/project/settings), скроллит вся
// панель целиком, а не каждая секция.
function Panel({ icon, title, chip, right, open, onToggle, children }) {
  return (<>
    <ListItemButton dense onClick={onToggle} sx={{ px: 1.5, py: 0.5 }}>
      {open ? <ExpandLessIcon sx={{ fontSize: 18 }} />
            : <ExpandMoreIcon sx={{ fontSize: 18 }} />}
      {icon}
      <Typography variant="body2" sx={{ fontWeight: 500, ml: 0.5 }}>
        {title}
      </Typography>
      <Box sx={{ ml: "auto", display: "flex", alignItems: "center",
                 gap: 0.5 }}
           onClick={e => e.stopPropagation()}>
        {chip}
        {right}
      </Box>
    </ListItemButton>
    <Collapse in={open}>{children}</Collapse>
  </>);
}

// «тот же цвет, но ярче» — рамка целевой колонки: оттенок фона темы
// с поднятой насыщенностью и опущенной светлотой (hex6 → hex6)
const boostColor = hex => {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || "");
  if (!m) return "";
  const [r, g, b] = m.slice(1).map(v => parseInt(v, 16) / 255);
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let h = 0;
  if (d) {
    const hi = mx === r ? ((g - b) / d) % 6
             : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    h = (hi * 60 + 360) % 360;
  }
  const l = (mx + mn) / 2;
  const s = d ? Math.min(1, Math.max(
      d / (1 - Math.abs(2 * l - 1)) * 1.5, 0.55)) : 0.55;
  const l2 = 0.5;
  const c = (1 - Math.abs(2 * l2 - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const seg = [[c, x, 0], [x, c, 0], [0, c, x],
               [0, x, c], [x, 0, c], [c, 0, x]][Math.floor(h / 60) % 6];
  const o = Math.round((l2 - c / 2) * 255);
  const f = v => (Math.round(v * 255) + o).toString(16).padStart(2, "0");
  return "#" + f(seg[0]) + f(seg[1]) + f(seg[2]);
};

// Колонка канбан-доски тем: заголовок (имя, 🔁-сессия, счётчик задач,
// меню ⋯) + ряд чипов эффективных настроек (тема → проект →
// глобальные; залитый чип = задано у самой темы) + карточки задач +
// кнопка «＋ задача сюда». Клик по заголовку делает колонку «целевой»
// — новые задачи падают в неё (рамка — яркая версия цвета темы).
// «Главная» не удаляется, но переименовывается — имя в «⚙ Настройки»
// (ключ name в pj:<p>.tmain).
function TopicColumn({ name, sess, count, sel, accent, color, tset,
                      eff, onSelect, onNewTask, onDelete,
                      onSettings, onMoveL, onMoveR,
                      empty, children, more, busy, onMore,
                      onBodyOver, onBodyDrop, loading,
                      onDict, dictOn, onStats, pending }) {
  const [menu, setMenu] = useState(null);
  return (
    <Paper variant="outlined" sx={{ position: "relative",
      width: { xs: "82vw", sm: 300, md: 320 }, flexShrink: 0,
      // minHeight:0 — иначе длинный список растягивает колонку
      // (min-height:auto у flex-item'а) и всю страницу за собой;
      // высота колонки фиксирована — крутится только список внутри
      height: "100%", minHeight: 0,
      display: "flex", flexDirection: "column",
      borderRadius: "12px", scrollSnapAlign: "start",
      borderColor: sel ? (boostColor(color) || accent || "primary.main")
                       : "divider",
      borderWidth: sel ? 2 : 1,
      bgcolor: color || "background.paper" }}>
      {pending && <PendOverlay />}
      <Box onClick={onSelect}
           sx={{ display: "flex", alignItems: "center", gap: 0.6,
                 px: 1.1, py: 0.7, cursor: "pointer", flexShrink: 0,
                 borderBottom: "1px solid", borderColor: "divider" }}>
        <Tooltip title={sel
            ? "целевая колонка — новые задачи падают сюда"
            : "клик — новые задачи будут падать в эту тему"}>
          <Typography variant="body2" noWrap
                      sx={{ flex: 1, minWidth: 0, fontWeight: 600,
                            fontSize: 13 }}>
            {name}
          </Typography>
        </Tooltip>
        {sess &&
          <Tooltip title="закреплённая devin-сессия — следующая задача темы продолжит её">
            <Typography component="span" sx={{ fontSize: 12,
                        lineHeight: 1, flexShrink: 0 }}>🔁</Typography>
          </Tooltip>}
        <Chip size="small" label={count}
              sx={{ height: 17, fontSize: 10.5, flexShrink: 0 }} />
        {(onDelete || onSettings || onMoveL || onMoveR || onStats) &&
          <>
            <Tooltip title="действия с темой">
              <IconButton size="small" sx={{ p: 0.2 }}
                onClick={e => { e.stopPropagation();
                                setMenu(e.currentTarget); }}>
                <MoreVertIcon sx={{ fontSize: 15 }} />
              </IconButton>
            </Tooltip>
            <Menu anchorEl={menu} open={!!menu}
                  onClose={() => setMenu(null)}
                  onClick={e => e.stopPropagation()}>
              {onStats &&
                <MenuItem dense sx={{ fontSize: 13 }}
                  onClick={() => { setMenu(null); onStats(); }}>
                  📊 Статистика
                </MenuItem>}
              {onSettings &&
                <MenuItem dense sx={{ fontSize: 13 }}
                  onClick={() => { setMenu(null); onSettings(); }}>
                  ⚙ Настройки
                </MenuItem>}
              {onMoveL &&
                <MenuItem dense sx={{ fontSize: 13 }}
                  onClick={() => { setMenu(null); onMoveL(); }}>
                  ⬅ Сместить влево
                </MenuItem>}
              {onMoveR &&
                <MenuItem dense sx={{ fontSize: 13 }}
                  onClick={() => { setMenu(null); onMoveR(); }}>
                  ➡ Сместить вправо
                </MenuItem>}
              {onDelete &&
                <MenuItem dense sx={{ fontSize: 13, color: "error.main" }}
                  onClick={() => { setMenu(null); onDelete(); }}>
                  🗑 Удалить тему
                </MenuItem>}
            </Menu>
          </>}
      </Box>
      {eff &&
        // эффективные настройки колонки тегами — видно, с чем уходят
        // задачи темы; залитый чип = переопределено у самой темы,
        // контурный — наследуется из проекта/настроек
        <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.4,
                   px: 0.9, py: 0.5, flexShrink: 0,
                   borderBottom: "1px solid", borderColor: "divider" }}>
          {tset?.own_session === 0 &&
            <Tooltip title={tset.session_topic_id
                     ? "сессия прицепленной темы «" +
                       (tset.attach_name
                        || "тема #" + tset.session_topic_id) +
                       "» — своя у этой не создаётся"
                     : "общая сессия проекта — у темы нет своей," +
                       " задачи идут как в «Главной»"}>
              <Chip size="small" variant="outlined"
                    label={tset.session_topic_id
                      ? "🔗 → " + (tset.attach_name
                          || "тема #" + tset.session_topic_id)
                      : "🔗 общая"}
                    sx={{ height: 17, fontSize: 9.5, fontWeight: 500,
                          borderRadius: "6px" }} />
            </Tooltip>}
          {[
            [eff.reply_mode === "say" ? "📝 заметка"
              : eff.reply_mode === "ask" ? "💬 спросить" : "🛠 код",
             tset?.reply_mode, "режим ответа"],
            [eff.auto_commit === "1" ? "⚡ автокоммит" : "✋ коммит вручную",
             tset?.auto_commit, "автокоммит после задачи"],
            [eff.model ? "М: " + eff.model : null,
             tset?.model, "модель"],
            [eff.fast === "1" ? "⚡ быстрый" : "обычный",
             tset?.fast, "быстрый режим — голос сразу в задачу"],
          ].filter(([label]) => label).map(([label, own, hint]) => (
            <Tooltip key={hint}
                     title={hint + (own
                       ? " — задано у темы" : " — из настроек проекта")}>
              <Chip size="small" label={label}
                    color={own ? "primary" : "default"}
                    variant={own ? "filled" : "outlined"}
                    sx={{ height: 17, fontSize: 9.5, fontWeight: 500,
                          borderRadius: "6px",
                          "& .MuiChip-label": { px: "6px" } }} />
            </Tooltip>))}
        </Box>}
      <Box sx={{ px: 0.8, pt: 0.8, flexShrink: 0 }}>
        {(() => { const btnC = boostColor(color) || accent
                                || "#5e6ad2";
          return (
            <Box sx={{ display: "flex", gap: 0.5 }}>
            <Button size="small" onClick={onNewTask}
                    sx={{ flex: 1, textTransform: "none", fontSize: 13,
                          py: 0.6, fontWeight: 600,
                          border: "1.5px dashed", borderRadius: "9px",
                          color: btnC, borderColor: btnC,
                          "&:hover": { bgcolor:
                            btnC.startsWith("#") ? btnC + "14"
                                                 : "action.hover" } }}>
              {eff?.reply_mode === "say" ? "＋ заметка"
                : eff?.reply_mode === "ask" ? "＋ спросить"
                : "＋ задача"}
            </Button>
            {onDict &&
              <Tooltip title={dictOn
                ? "стоп запись"
                : "надиктовать — текст в композер; в быстром режиме задача сразу в эту колонку"}>
                <IconButton size="small"
                  onClick={e => { e.stopPropagation(); onDict(); }}
                  sx={{ border: "1.5px dashed", borderRadius: "9px",
                        width: 32, flexShrink: 0,
                        color: dictOn ? "error.main" : btnC,
                        borderColor: dictOn ? "error.main" : btnC }}>
                  {dictOn ? <StopIcon sx={{ fontSize: 15 }} />
                          : <MicIcon sx={{ fontSize: 15 }} />}
                </IconButton>
              </Tooltip>}
            </Box>); })()}
      </Box>
      <Box sx={{ p: 0.8, display: "flex", flexDirection: "column",
                 gap: 0.8, flex: 1, minHeight: 0, overflowY: "auto",
                 "& > *": { flexShrink: 0 },
                 "&::-webkit-scrollbar": { width: 8 } }}
           onDragOver={onBodyOver} onDrop={onBodyDrop}>
        {children}
        {loading && !React.Children.count(children) &&
          [0, 1, 2].map(i => (
            <Skeleton key={i} variant="rounded" height={76}
                      sx={{ borderRadius: "10px", flexShrink: 0 }} />))}
        {!React.Children.count(children) && !loading &&
          <Typography variant="caption" color="text.secondary"
                      align="center" sx={{ py: 2, display: "block" }}>
            {empty || "нет задач"}
          </Typography>}
        {more &&
          <Button size="small" fullWidth onClick={onMore}
                  disabled={busy}
                  sx={{ textTransform: "none", fontSize: 12, py: 0.3,
                        color: "text.secondary" }}>
            {busy ? "загружаю…" : "загрузить ещё"}
          </Button>}
      </Box>
    </Paper>
  );
}

export default function App() {
  const [projects, setProjects] = useState([]);
  const [multiMode, setMultiMode] = useState(false);
  const [project, setProject] = useState(null);
  const projRef = useRef(null);
  // тема: «main» — главная; число (строкой) — именованная тема проекта
  const [topicSel, setTopicSel] = useState("main");
  const topicRef = useRef("main");
  const [topics, setTopics] = useState([]);
  // выбранная карточка-заметка («нажатая»): композер в режиме
  // «сказать» дописывает в неё текст — повторный клик отжимает
  const [noteSel, setNoteSel] = useState(null);
  // «продолжить» на done-карточке: композер дописывает доделку
  // в её задачу, та уходит обратно в queued (той же сессией)
  const [contSel, setContSel] = useState(null);
  // список тем текущего проекта уже загружен — можно проверять,
  // не удалили ли сохранённую тему
  const topicsLoaded = useRef(false);
  const [feed, setFeed] = useState(new Map());
  const [booted, setBooted] = useState(false); // до первой загрузки — скелетон
  // «загрузить ещё» в колонках канбана: ключ (main|tid) → has_more /
  // идёт загрузка следующей страницы
  const [colMore, setColMore] = useState({});
  const [colBusy, setColBusy] = useState({});
  const [status, setStatus] = useState({});
  const [models, setModels] = useState({ models: [], current: "" });
  const [mode, setMode] = useState("code");
  const [fast, setFast] = useState(false);       // дефолт проекта (pj)
  const [fastOv, setFastOv] = useState(null);    // сессионный оверрайд
  const [mainDef, setMainDef] = useState({});    // настройки «Главной»
  const [tSetDlg, setTSetDlg] = useState(null);  // диалог настроек темы
  const [panels, setPanels] = useState({ files: true, changes: true,
                                        builds: true, hooks: true,
                                        ws: true, branches: true,
                                        instr: true, deploy: true });
  const [toast, setToast] = useState(null);
  const [toastNode, setToastNode] = useState(null);
  const [projIcon, setProjIcon] = useState(""); // иконка активного проекта
  const [projColor, setProjColor] = useState(""); // цвет активного проекта
  const [colorPreview, setColorPreview] = useState(null); // превью из диалога настроек
  const [profileOpen, setProfileOpen] = useState(false);
  const [profMenu, setProfMenu] = useState(null);  // anchor профиля
  const [keysOpen, setKeysOpen] = useState(false); // «Ключи репозиториев»
  const [setOpen, setSetOpen] = useState(false);   // «Настройки»
  const [usersOpen, setUsersOpen] = useState(false); // «Пользователи» (админ)
  const [wsOpen, setWsOpen] = useState(false);   // «Рабочее пространство»
  const [branchDlg, setBranchDlg] = useState(null); // «🌿 новая ветка»
  const [browseOpen, setBrowseOpen] = useState(false);
  const [addPreset, setAddPreset] = useState(null);
  const [branchName, setBranchName] = useState("");
  const [wsInfo, setWsInfo] = useState({ ws: [], active: 0 });
  const [wsmap, setWsmap] = useState({});        // project -> ws id
  const [view, setView] = useState("feed");      // feed | models
  const [pSetOpen, setPSetOpen] = useState(null); // настройки проекта
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [pw, setPw] = useState({ cur: "", n1: "", n2: "" });
  const [treeVer, setTreeVer] = useState(0);
  const [editPath, setEditPath] = useState(null);   // file open in editor
  const [addOpen, setAddOpen] = useState(false);    // add-project dialog
  // shared confirm dialog: {kind:"stop"|"cancel", name, stem} | null
  const [confirm, setConfirm] = useState(null);
  // диалог «📊 Статистика» темы: {key: 'main'|topic_id, name}
  const [statDlg, setStatDlg] = useState(null);
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
  // мобильная версия: двойной тап по открытой модалке закрывает её —
  // MUI-диалоги реагируют на Escape, шлём его на корни всех модалок
  // строкой, не коллбэком по теме: ThemeProvider рендерится ВНУТРИ
  // App, на уровне хуков контекста темы ещё нет (t → null → падение)
  const mob = useMediaQuery(theme.breakpoints.down("md"));
  // высота фиксированного композера — доска заканчивается прямо
  // над ним (зазор = верхнему отступу), без запаса «на глаз»:
  // высота бара плавает (ряд чипов, мобильная навигация)
  const [compH, setCompH] = useState(0);
  useEffect(() => {
    const el = document.getElementById("composer-bar");
    if (!el) { setCompH(0); return; }
    const f = () => setCompH(el.offsetHeight);
    f();
    const ro = new ResizeObserver(f);
    ro.observe(el);
    return () => ro.disconnect();
  }, [project, mob]);
  useEffect(() => {
    if (!mob) return;
    let lastT = 0, lastX = 0, lastY = 0;
    const h = e => {
      const t0 = e.changedTouches[0];
      if (!t0) return;
      const now = Date.now(), x = t0.clientX, y = t0.clientY;
      const dbl = now - lastT < 350 &&
                  Math.hypot(x - lastX, y - lastY) < 32;
      lastT = now; lastX = x; lastY = y;
      if (dbl)
        document.querySelectorAll(".MuiModal-root").forEach(m =>
          m.dispatchEvent(new KeyboardEvent("keydown",
            { key: "Escape", bubbles: true })));
    };
    document.addEventListener("touchend", h);
    return () => document.removeEventListener("touchend", h);
  }, [mob]);
  const modelFocus = useRef(false), modeFocus = useRef(false);

  // свежие сверху: порядок в колонке — tasks.sort (dnd-перестановка),
  // у записей до появления поля он равен created
  const items = useMemo(() =>
    [...feed.values()].sort((a, b) =>
      ((b.sort ?? b.created) - (a.sort ?? a.created))
      || b.created - a.created), [feed]);
  // канбан: главная колонка — задачи без темы; именованные — по tid
  const mainItems = items.filter(t => !t.tid);
  const byTopic = id => items.filter(t => t.tid === id);
  // задачи темы, которой ещё нет в списке topics (гонка опроса) —
  // вынесены в отдельную временную колонку
  const orphanTids = useMemo(() => {
    const known = new Set(topics.map(t => t.id));
    const s = new Set();
    items.forEach(t => { if (t.tid && !known.has(t.tid)) s.add(t.tid); });
    return [...s];
  }, [items, topics]);
  // имя целевой темы — показываем в чипе композера
  const topicName = topicSel === "main" ? (mainDef.name || "Главная")
    : (topics.find(t => String(t.id) === topicSel)?.name
       || "тема #" + topicSel);
  // настройки выбранной колонки (тема → «главная») — дефолты чипов
  // композера и быстрого режима
  const selTdef = topicSel === "main" ? mainDef
    : (topics.find(t => String(t.id) === topicSel) || {});
  // все колонки доски в порядке показа (sort): key, имя и
  // эффективный режим — для диалогов «переместить»/«в работу»
  const boardCols = useMemo(() => [
    { key: "main", sort: mainDef.sort || 0,
      name: mainDef.name ? "⭐ " + mainDef.name : "⭐ Главная",
      mode: (mainDef.eff || {}).reply_mode || "code" },
    ...topics.map(t => ({
      key: String(t.id), sort: t.sort || t.id,
      name: t.name || ("тема #" + t.id),
      mode: ((t.eff || {}).reply_mode) || "code" })),
  ].sort((a, b) => (a.sort - b.sort)
           || String(a.key).localeCompare(String(b.key))),
  [topics, mainDef]);
  // быстрый режим: сессионный оверрайд → дефолт колонки → проект
  const effFast = fastOv ?? (selTdef.fast === "1" ? true
                  : selTdef.fast === "0" ? false : fast);
  const toggleFast = () => {
    setFastOv(!effFast);
    setToast(!effFast ? "Быстрый режим — голос сразу в работу"
                      : "Обычный режим");
  };
  // смена целевой колонки/проекта — берём её дефолт быстрого режима
  useEffect(() => { setFastOv(null); }, [topicSel, project]);

  const loadTasks = useCallback(async () => {
    const p = projRef.current;
    if (!p) return;
    try {
      // канбан: у каждой колонки своя выдача — по 20 свежих задач,
      // «загрузить ещё» внизу колонки догружает её страницы
      let tkeys = ["main"];
      try {
        const td = await apiJson("/api/topics?project=" +
          encodeURIComponent(p));
        if (td.ok) {
          topicsLoaded.current = true;
          // сохраняем ссылочную стабильность: новые массив/объект
          // каждый поллинг сносили бы React.memo(TaskCard) — все
          // карточки перерисовывались и выделение текста умирало
          const nt = td.topics || [], nm = td.main || {};
          setTopics(prev =>
            JSON.stringify(prev) === JSON.stringify(nt) ? prev : nt);
          setMainDef(prev =>
            JSON.stringify(prev) === JSON.stringify(nm) ? prev : nm);
          tkeys = ["main", ...nt.map(t => String(t.id))];
        }
      } catch (e) { /* темы не пришли — опрашиваем хотя бы главную */ }
      const pages = await Promise.all(tkeys.map(k =>
        apiJson("/api/tasks?project=" + encodeURIComponent(p) +
          "&topic=" + k + "&limit=20")
          .then(d => ({ k, tasks: d.tasks || [],
                        hasMore: !!d.has_more }))
          .catch(() => null)));
      setFeed(m => {
        // выкидываем задачи чужих проектов — ответ опроса за старый
        // проект мог прилететь уже после переключения ws и висеть вечно
        const n = new Map([...m].filter(
          ([, t]) => !t.project || t.project === p));
        // keep object identity for unchanged tasks (h = server-side
        // content hash) — React.memo(TaskCard) then skips re-render and
        // the feed stops flickering on identical polls
        pages.forEach(pg => pg && pg.tasks.forEach(t => {
          const prev = n.get(t.stem);
          if (!prev || prev.h !== t.h) n.set(t.stem, t);
        }));
        return n;
      });
      setColMore(prev => {
        const n = { ...prev };
        pages.forEach(pg => { if (pg) n[pg.k] = pg.hasMore; });
        return n;
      });
      setBooted(true);   // первая порция — скелетон убираем
    } catch (e) {}
  }, []);

  // «загрузить ещё» внизу колонки: следующая страница (20) — задачи
  // старше самой старой показанной в этой теме
  const loadColMore = async key => {
    const p = projRef.current;
    if (!p || colBusy[key]) return;
    const colItems = key === "main" ? mainItems : byTopic(+key);
    const before = colItems.length
      ? colItems[colItems.length - 1].stem : null;
    if (!before) return;
    setColBusy(s => ({ ...s, [key]: true }));
    try {
      const d = await apiJson("/api/tasks?project=" +
        encodeURIComponent(p) + "&topic=" + key +
        "&limit=20&before=" + encodeURIComponent(before));
      setFeed(m => {
        const n = new Map(m);
        (d.tasks || []).forEach(t => {
          const prev = n.get(t.stem);
          if (!prev || prev.h !== t.h) n.set(t.stem, t);
        });
        return n;
      });
      setColMore(s => ({ ...s, [key]: !!d.has_more }));
    } catch (e) {}
    setColBusy(s => ({ ...s, [key]: false }));
  };

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
      setFast(d.fast === "1");
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
      setWsmap(d.wsmap || {});
      if (d.projects.length) {
        setProjects(d.projects); setMultiMode(true);
        // смена пространства → если текущий проект пропал из списка,
        // выбираем первый доступный (status.current — серверный fallback)
        if (!d.projects.includes(projRef.current))
          selectProject(d.current || d.projects[0]);
      }
    } catch (e) {}
  };

  const loadWs = () => apiJson("/api/ws")
    .then(j => setWsInfo({ ws: j.ws || [], active: j.active || 0 }))
    .catch(() => {});
  const wsColor = (wsInfo.ws.find(w => w.id === wsInfo.active) || {})
    .color || "#5e6ad2";
  // акцент приложения: превью из диалога → цвет проекта → цвет пространства
  const accent = (colorPreview ?? projColor) || wsColor;

  // drag&drop карточек по канбану (десктоп): карту тащат за
  // ручку-гриппер, колонка ловит dragover/drop — место вставки видно
  // по пунктирному плейсхолдеру; drop уходит в /api/task/move —
  // там же решается уровневый переход (повышение уровня = запуск)
  const [dropAt, setDropAt] = useState(null);  // {col, idx}
  // «честные» действия: ключ (stem карточки / col:<key> колонки) под
  // скелетоном, пока сервер не ответил и лента не перечитана
  const [pendSet, setPendSet] = useState(() => new Set());
  // убрать карточку из ленты локально (бэк уже стёр её: retry_of,
  // merge) — поллинг Map только мержит, удалённых не выкидывает
  const dropStem = useCallback(stem => setFeed(m => {
    const n = new Map(m); n.delete(stem); return n; }), []);
  const pendRun = useCallback(async (k, fn) => {
    setPendSet(p => new Set(p).add(k));
    try {
      const d = await fn();
      if (d?.ok) await loadTasks();
      return d;
    } finally {
      setPendSet(p => { const n = new Set(p); n.delete(k); return n; });
    }
  }, [loadTasks]);
  const dropAtRef = useRef(null);
  const setDrop = useCallback(
    d => { dropAtRef.current = d; setDropAt(d); }, []);
  // склейка заметок: note-карту можно бросить на другую note (даже в
  // другой колонке) — цель подсвечивается пунктиром, drop льёт текст
  // источника в цель новым абзацем и стирает источник
  const [mergeAt, setMergeAt] = useState(null);
  const mergeOver = useCallback((e, t) => {
    const types = e.dataTransfer ? [...e.dataTransfer.types] : [];
    if (!types.includes("text/plain") || !dragStemNow?.note ||
        t.stem === dragStemNow.stem) return;
    e.preventDefault(); e.stopPropagation();
    e.dataTransfer.dropEffect = "move";
    setDrop(null);
    setMergeAt(prev => prev === t.stem ? prev : t.stem);
  }, [setDrop]);
  const mergeLeave = useCallback(t =>
    setMergeAt(prev => prev === t.stem ? null : prev), []);
  const mergeDrop = useCallback((e, t) => {
    e.preventDefault(); e.stopPropagation();
    const stem = e.dataTransfer.getData("text/plain");
    setMergeAt(null);
    if (!stem || stem === t.stem || !dragStemNow?.note) return;
    pendRun(t.stem, () => post("/api/task/merge",
                               { from: stem, to: t.stem })).then(res => {
      if (res.ok) { dropStem(stem); setToast("Заметки объединены"); }
      else setToast("Объединение: " + (res.error || "?"));
    }).catch(() => setToast("Сеть: не объединил заметки"));
  }, [pendRun, dropStem]);
  // отпустили карту вне колонки — спрятать плейсхолдер
  useEffect(() => {
    const clear = () => { setDrop(null); setMergeAt(null); };
    document.addEventListener("dragend", clear);
    document.addEventListener("drop", clear);
    return () => { document.removeEventListener("dragend", clear);
                   document.removeEventListener("drop", clear); };
  }, []);
  const overCol = (e, key) => {
    const types = e.dataTransfer ? [...e.dataTransfer.types] : [];
    if (!types.includes("text/plain")) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    // место вставки = индекс первой карты, чья середина ниже курсора
    const cards = [...e.currentTarget.querySelectorAll("[data-stem]")];
    let idx = cards.length;
    for (let i = 0; i < cards.length; i++) {
      const r = cards[i].getBoundingClientRect();
      if (e.clientY < r.top + r.height / 2) { idx = i; break; }
    }
    const d = dropAtRef.current;
    if (!d || d.col !== key || d.idx !== idx)
      setDrop({ col: key, idx });
  };
  const dropCol = (e, key) => {
    e.preventDefault();
    const stem = e.dataTransfer.getData("text/plain");
    const d = dropAtRef.current;
    setDrop(null);
    if (!stem) return;
    const stems = (key === "main" ? mainItems : byTopic(+key))
      .map(t => t.stem);
    let idx = d && d.col === key ? d.idx : stems.length;
    // перетаскиваемую карту убираем из списка соседей — если она
    // стояла выше точки вставки, индекс сдвигается
    const si = stems.indexOf(stem);
    const fl = stems.filter(s => s !== stem);
    if (si !== -1 && si < idx) idx -= 1;
    idx = Math.max(0, Math.min(idx, fl.length));
    const body = { stem, topic: key };
    if (fl[idx - 1]) body.above = fl[idx - 1];
    if (fl[idx]) body.below = fl[idx];
    pendRun(stem, () => post("/api/task/move", body)).then(res => {
      if (!res.ok) setToast("Перенос: " + (res.error || "?"));
      else if (res.started) setToast("▶ Карточка запущена");
    }).catch(() => setToast("Сеть: не перенёс карточку"));
  };
  // карточки колонки с пунктирным плейсхолдером в месте вставки
  const colCards = (list, key) => {
    const out = [];
    const mark = (
      <Box key="__drop" sx={{
        height: 54, borderRadius: "12px",
        border: "1.5px dashed", borderColor: accent || "primary.main",
        bgcolor: "rgba(94,106,210,.05)" }} />);
    list.forEach((t, i) => {
      if (dropAt?.col === key && dropAt.idx === i) out.push(mark);
      out.push(
        <TaskCard key={t.stem} t={t} hideTopic
          sel={noteSel === t.stem || contSel === t.stem}
          onNote={toggleNote} onCont={toggleCont}
          onStop={askStop} onCancel={askCancel}
          onDel={askDel} toast={setToast} cols={boardCols}
          onDict={toggleDict}
          dictOn={dict?.kind === "note" && dict?.stem === t.stem}
          pending={pendSet.has(t.stem)}
          pend={pendRun}
          onGone={dropStem}
          mergeSel={mergeAt === t.stem}
          onMergeOver={mergeOver}
          onMergeDrop={mergeDrop}
          onMergeLeave={mergeLeave} />);
    });
    if (dropAt?.col === key && dropAt.idx >= list.length)
      out.push(mark);
    return out;
  };

  const selectProject = useCallback(p => {
    setProject(p); projRef.current = p;
    // тема проекта восстанавливается — выбор живёт в localStorage
    const tsel = loadTopicMap()[p] || "main";
    setTopicSel(tsel); topicRef.current = tsel;
    setTopics([]); topicsLoaded.current = false;
    if (multiMode)
      post("/api/project", { project: p })
        .then(d => { if (!d.ok) setToast("Проект: " + (d.error || "?")); })
        .catch(() => {});
    // проект из другого пространства → переключаем и его (цвет, списки)
    const pws = wsmap[p];
    if (pws && pws !== wsInfo.active)
      post("/api/ws/active", { id: pws })
        .then(() => { loadWs(); refreshProjects(); })
        .catch(() => {});
    setFeed(new Map()); setColMore({}); setColBusy({});
    setNoteSel(null); setContSel(null);
    setDrawerOpen(false);
    loadTasks();
  }, [multiMode, loadTasks, wsmap, wsInfo]);

  // целевая тема: клик по колонке канбана решает, куда упадут новые
  // задачи; лента общая — перезагружать её не нужно
  const selectTopic = v => {
    setTopicSel(v); topicRef.current = v;
    saveTopicSel(projRef.current, v);
  };
  // сохранённая тема могла быть удалена — откатываемся на «Главную»
  // (но только когда список тем уже пришёл, не на пустом старте)
  useEffect(() => {
    if (topicsLoaded.current && topicSel !== "main" &&
        !topics.some(t => String(t.id) === topicSel))
      selectTopic("main");
  }, [topics]);
  // «＋ Новая тема» — диалог настроек колонки (название, цвет,
  // дефолты задач); сохранение выбирает её целевой
  const createTopic = () => setTSetDlg({ kind: "create" });
  // «◀/▶» в меню колонки — сдвиг темы на доске; «Главная» всегда
  // первая и не двигается
  const moveTopic = (id, dir) =>
    pendRun("col:" + id, () =>
      post("/api/topics", { action: "move", project: projRef.current,
                            id, dir }))
      .then(async d => {
        if (!d.ok) return setToast("Тема: " + (d.error || "?"));
        const td = await apiJson("/api/topics?project=" +
          encodeURIComponent(projRef.current)).catch(() => null);
        if (td?.ok) {
          const nt = td.topics || [], nm = td.main || {};
          setTopics(prev =>
            JSON.stringify(prev) === JSON.stringify(nt) ? prev : nt);
          setMainDef(prev =>
            JSON.stringify(prev) === JSON.stringify(nm) ? prev : nm);
        }
      })
      .catch(() => setToast("Сеть: не сдвинул тему"));
  // удаление темы: карточки уходят каскадом вместе с ней, но если
  // хоть одна в очереди/в работе — показываем блок в диалоге
  // (бэк тоже вернёт 409 с именем задачи)
  const askDelTopic = (id, name) => {
    const act = byTopic(id)
      .filter(t => t.status === "running" || t.status === "queued");
    setConfirm({ kind: "topic_del", tid: id, name,
                 active: act.map(t => t.name),
                 cards: byTopic(id).length });
  };
  // вкладки проектов: открытые проекты — ряд вкладок слева от «+»;
  // хранятся в localStorage, закрытая активная → соседняя или пусто
  const [tabs, setTabs] = useState(() => {
    try { return JSON.parse(localStorage.getItem("devin.ptabs") || "[]"); }
    catch { return []; }
  });
  useEffect(() => {
    try { localStorage.setItem("devin.ptabs", JSON.stringify(tabs)); }
    catch {}
  }, [tabs]);
  useEffect(() => {
    if (projects.length)
      setTabs(ts => ts.filter(t => projects.includes(t)));
  }, [projects]);
  useEffect(() => {
    if (project && !tabs.includes(project))
      setTabs(ts => [...ts, project]);
  }, [project]);   // eslint-disable-line react-hooks/exhaustive-deps
  const closeTab = p => {
    const nt = tabs.filter(t => t !== p);
    setTabs(nt);
    if (p !== project) return;
    const nxt = nt[nt.length - 1] || null;
    if (nxt) switchTab(nxt);
    else { setProject(null); projRef.current = null;
           setFeed(new Map()); }
  };
  // переключение вкладки — полная перезагрузка: POST проекта и
  // смены пространства должны успеть уйти, дальше всё (цвет,
  // иконка, настройки) подтянется с сервера
  const switchTab = async p => {
    const pws = wsmap[p];
    try {
      if (pws && pws !== wsInfo.active)
        await post("/api/ws/active", { id: pws });
      await post("/api/project", { project: p });
    } catch {}
    location.reload();
  };

  // диктовка: 🎙 на note-карточке дописывает текст в неё
  // (/api/task/append), 🎙 у «＋ … сюда» в колонке — голос →
  // /api/stt → быстрый режим: задача сразу в эту колонку её
  // уровня, обычный: текст попадает в поле композера, а колонка
  // становится целевой
  const dictRef = useRef(null);
  const [dict, setDict] = useState(null);   // {kind:'note'|'col',...}
  const [dictInfo, setDictInfo] = useState("");
  const [compInj, setCompInj] = useState({ text: "", n: 0 });
  // продиктованная командная фраза в начале речи — «заметка сюда»,
  // «задача сюда», «спросить», «плюс задача» — не часть текста,
  // срезаем её, чтобы не уходила в промпт/заметку
  const cleanDictText = t => t.replace(
    /^\s*(плюс\s*)?(новая\s+|новый\s+)?(заметк\w*|задач\w*|спрос\w*)(\s+сюда)?[\s,.:;—-]*/u,
    "").trim();
  const stopDict = async () => {
    const r = dictRef.current;
    if (!r) return;
    dictRef.current = null;
    setDict(null); setDictInfo("");
    clearTimeout(r.timer); clearInterval(r.clock);
    r.proc.disconnect(); r.src.disconnect(); r.gain.disconnect();
    r.stream.getTracks().forEach(t => t.stop());
    const wav = encodeWav(
      resample(r.chunks, r.ctx.sampleRate, STT_RATE), STT_RATE);
    r.ctx.close();
    setNoteSel(null);
    try {
      const d = await (await fetch("/api/stt", { method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: wav })).json();
      const txt = cleanDictText((d.text || "").trim());
      if (!d.ok || !txt) {
        setToast(d.ok ? "Ничего не распознано"
                      : "STT: " + (d.error || "?"));
      } else if (r.target.kind === "note") {
        const a = await post("/api/task/append",
                             { stem: r.target.stem, text: txt });
        setToast(a.ok ? "Дописано в заметку"
                      : "append: " + (a.error || "?"));
        loadTasks();
      } else if (effFast) {
        const a = await post("/api/tasks", {
          project: project === "workspace" ? null : project,
          text: txt, topic: r.target.key,
          ...(r.target.mode === "say" ? { mode: "say" } : {}),
          ...(r.target.mode === "ask" ? { mode: "ask" } : {}) });
        setToast(a.ok ? "Задача поставлена"
                      : "Ошибка: " + (a.error || "?"));
        loadTasks();
      } else {
        setCompInj(c => ({ text: txt, n: c.n + 1 }));
        document.getElementById("composer-input")?.focus();
      }
    } catch (e) { setToast("STT сеть: " + e); }
  };
  const startDict = async target => {
    try {
      const stream = await navigator.mediaDevices
        .getUserMedia({ audio: true });
      const ctx = new (window.AudioContext
        || window.webkitAudioContext)({ sampleRate: STT_RATE });
      const src = ctx.createMediaStreamSource(stream);
      const proc = ctx.createScriptProcessor(4096, 1, 1);
      const gain = ctx.createGain(); gain.gain.value = 0;
      const chunks = [];
      proc.onaudioprocess = e => chunks.push(
        new Float32Array(e.inputBuffer.getChannelData(0)));
      src.connect(proc); proc.connect(gain);
      gain.connect(ctx.destination);
      const t0 = Date.now();
      dictRef.current = { target, ctx, proc, src, gain, stream,
        chunks,
        clock: setInterval(() => setDictInfo(
          new Date(Date.now() - t0).toISOString().substr(14, 5)), 250),
        timer: setTimeout(stopDict, 300000) };
      setDict(target); setDictInfo("00:00");
    } catch (e) {
      setToast("Микрофон: " + e);
      setDict(null); setNoteSel(null);
    }
  };
  const toggleDict = t => {
    if (dictRef.current) { stopDict(); return; }
    setNoteSel(t.stem);
    startDict({ kind: "note", stem: t.stem });
  };
  const toggleDictCol = (key, mode) => {
    if (dictRef.current) { stopDict(); return; }
    selectTopic(key);
    startDict({ kind: "col", key, mode });
  };

  // «＋ задача сюда» в колонке: выбирает тему целевой и фокусирует
  // поле ввода композера
  const newTaskIn = v => {
    selectTopic(v);
    document.getElementById("composer-input")?.focus();
  };

  // раскрытые секции панели — per-user+project, подгружаем при смене проекта
  useEffect(() => {
    if (!project) return;
    setPanels({ files: true, changes: true, builds: true,
                hooks: true, ws: true, branches: true, instr: true, deploy: true });
    apiJson("/api/project/settings?project=" + encodeURIComponent(project))
      .then(d => { if (d.ok && d.panel)
        setPanels(s => ({ ...s, ...d.panel })); })
      .catch(() => {});
  }, [project]);

  const switchWs = id =>
    post("/api/ws/active", { id })
      .then(() => { loadWs(); refreshProjects(); })
      .catch(() => setToast("Сеть: не переключил пространство"));

  const togglePanel = k => setPanels(s => {
    const n = { ...s, [k]: !s[k] };
    post("/api/project/settings",
         { project: projRef.current, panel: n }).catch(() => {});
    return n;
  });

  // инфо о ветке/грязи репо — опрашиваем для верхнего бара
  const [brInfo, setBrInfo] = useState(null);
  const loadBranches = useCallback(async () => {
    const p = projRef.current;
    if (!p) return;
    try {
      const d = await apiJson("/api/branches?project=" +
        encodeURIComponent(p));
      if (d.ok) setBrInfo(d);
    } catch (e) {}
  }, []);
  useEffect(() => {
    loadBranches();
    const t = setInterval(loadBranches, 15000);
    return () => clearInterval(t);
  }, [project, loadBranches]);

  const repoCommit = async () => {
    try {
      const d = await post("/api/repo/commit", { project: projRef.current });
      setToast(d.ok ? "Закоммичено и запушено"
                    : "Ошибка: " + (d.error || "?"));
      if (d.ok) loadBranches();
    } catch (e) { setToast("Сеть: " + e); }
  };

  // стабильные колбэки — иначе memo-карточки ререндерятся на каждом опросе
  // и выделение текста слетает
  const askStop = useCallback(
    t2 => setConfirm({ kind: "stop", name: t2.name }), []);
  const askCancel = useCallback(
    t2 => setConfirm({ kind: "cancel", name: t2.name, stem: t2.stem }), []);
  const askDel = useCallback(
    t2 => setConfirm({ kind: "del", name: t2.name, stem: t2.stem }), []);
  // клик по карточке-заметке — «нажать»/«отжать» её
  const toggleNote = useCallback(t2 => {
    setContSel(null);
    setNoteSel(s => s === t2.stem ? null : t2.stem);
  }, []);
  // «↻ продолжить» на done-карточке — «нажать»/«отжать»
  const toggleCont = useCallback(t2 => {
    setNoteSel(null);
    setContSel(s => s === t2.stem ? null : t2.stem);
  }, []);
  // карточку запустили/удалили — она перестала быть заметкой:
  // выбор снимаем, композер возвращается в обычный режим
  useEffect(() => {
    if (noteSel && feed.get(noteSel)?.status !== "note")
      setNoteSel(null);
  }, [feed, noteSel]);
  // то же для «продолжения»: карточка ушла из done — отжать
  useEffect(() => {
    if (contSel && feed.get(contSel)?.status !== "done")
      setContSel(null);
  }, [feed, contSel]);
  const openBranchDlg = useCallback(() => {
    setBranchName(branchSuggest(""));
    setBranchDlg({ new: true });
  }, []);

  // initial project list + tasks; polling every 3 s
  useEffect(() => {
    (async () => {
      try {
        const d = await apiJson("/api/projects");
        setWsmap(d.wsmap || {}); loadWs();
        const projs = d.projects.length ? d.projects : ["workspace"];
        setProjects(projs); setMultiMode(!!d.projects.length);
        // онбординг: проектов нет → сначала ключи, потом репозиторий
        if (!d.projects.length && d.current === null)
          setKeysOpen(true);
        // ?project=X в URL — открыть конкретный проект; неизвестный
        // или чужой → обычный выбор (current/первый), параметр чистим
        const qp = new URLSearchParams(location.search).get("project");
        const cur = (qp && projs.includes(qp)) ? qp
                                              : (d.current || projs[0]);
        setProject(cur); projRef.current = cur;
        const tsel = loadTopicMap()[cur] || "main";
        setTopicSel(tsel); topicRef.current = tsel;
        if (qp) {
          history.replaceState(null, "", location.pathname);
          if (cur === qp && d.projects.length)
            post("/api/project", { project: cur }).catch(() => {});
        }
        loadTasks();
      } catch (e) {}
    })();
  }, [loadTasks]);

  // иконка и цвет проекта (pj:<name>.icon / .color) — в шапке
  const loadProjSettings = useCallback(() => {
    if (!project || project === "workspace") return;
    apiJson("/api/project/settings?project=" + encodeURIComponent(project))
      .then(j => { if (j.ok) { setProjIcon(j.icon || "");
                               setProjColor(j.color || ""); } })
      .catch(() => {});
  }, [project]);
  useEffect(() => {
    setProjIcon(""); setProjColor(""); setColorPreview(null);
    loadProjSettings();
  }, [loadProjSettings]);
  useEffect(() => {
    loadStatus(); loadModels();
    const t = setInterval(() => { loadStatus(); loadTasks(); loadModels(); }, 3000);
    return () => clearInterval(t);
  }, [loadStatus, loadTasks, loadModels]);

  // автоскролл ленты убран: поллинг (рост output у бегущей задачи)
  // не должен дёргать положение страницы — живой вывод и так идёт
  // внутри модалки 📄; на канбане свежие задачи сверху колонок,
  // stick-to-bottom работал в обратную сторону
  const statusText = (status.current_task ? "▶ " + status.current_task : "idle") +
    " · очередь " + (status.queue ?? "?") + " · " + (status.model || "");

  const setModel = m => post("/api/model", { model: m }).then(d => {
    setToast(d.ok ? "Модель: " + m : "Ошибка: " + (d.error || "?"));
    loadModels(); loadStatus();
  }).catch(() => {});

  const confirmAct = async () => {
    const c = confirm;
    setConfirm(null);
    const pk = c.kind === "topic_del" ? "col:" + c.tid : c.stem;
    try {
      const d = await pendRun(pk, async () => c.kind === "stop"
        ? await post("/api/stop", { stem: confirm.stem })
        : c.kind === "del"
        ? await post("/api/task/delete", { stem: c.stem })
        : c.kind === "topic_del"
        ? await post("/api/topics", { action: "delete",
                       project: projRef.current, id: c.tid })
        : await post("/api/task/cancel", { stem: c.stem }));
      if (d.ok) {
        setToast(c.kind === "stop" ? "⛔ Остановлено: " + d.stopped
                 : c.kind === "del" ? "🗑 Задача удалена"
                 : c.kind === "topic_del" ? "🗑 Тема удалена"
                                   : "Удалено из очереди: " + c.name);
        if (c.kind === "cancel" || c.kind === "del")
          setFeed(m => { const n = new Map(m); n.delete(c.stem); return n; });
        if (c.kind === "topic_del") {
          setTopics(ts => ts.filter(t => t.id !== c.tid));
          // её карточки стёрты каскадом — убираем из ленты
          setFeed(m => new Map(
            [...m].filter(([, t]) => t.tid !== c.tid)));
          if (topicSel === String(c.tid)) selectTopic("main");
        }
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
        <Typography component="span" variant="caption"
                    sx={{ opacity: .55, fontSize: 11 }}>
          (v{status.version || "…"})
        </Typography>
      </Box>
      <Instr project={project} open={panels.instr}
             onToggle={() => togglePanel("instr")} toast={setToast} />
      <Divider />
      <Panel title="Файлы" open={panels.files}
             onToggle={() => togglePanel("files")}
             icon={<FolderOpenIcon sx={{ fontSize: 16, ml: 0.5 }} />}
             right={
               <Tooltip title="обновить список файлов">
                 <IconButton size="small"
                             onClick={() => setTreeVer(v => v + 1)}>
                   <RefreshIcon sx={{ fontSize: 16 }} />
                 </IconButton>
               </Tooltip>}>
        <Box sx={{ px: 1 }}>
          <FileTree key={project + ":" + treeVer}
                    project={project} onError={setToast}
                    onOpenFile={setEditPath} />
        </Box>
      </Panel>
      <Divider />
      <Changes project={project} toast={setToast}
               open={panels.changes} onToggle={() => togglePanel("changes")}
               bOpen={panels.builds} onToggleB={() => togglePanel("builds")} />
      <Divider />
      <Branches project={project} open={panels.branches}
                onToggle={() => togglePanel("branches")}
                toast={setToast} />
      <Divider />
      <Panel title="Пространства" open={panels.ws}
             onToggle={() => togglePanel("ws")}
             icon={<WorkspacesIcon sx={{ fontSize: 16, ml: 0.5 }} />}
             chip={<Box sx={{ ml: 1, width: 18, height: 18,
                             borderRadius: "50%", bgcolor: wsColor,
                             color: "#fff", fontSize: 11, fontWeight: 600,
                             display: "flex", alignItems: "center",
                             justifyContent: "center" }}>
                     {wsInfo.ws.length}
                   </Box>}>
        <Box>
          {wsInfo.ws.map(w =>
            <ListItemButton key={w.id} dense
                            selected={w.id === wsInfo.active}
                            onClick={() =>
                              w.id !== wsInfo.active && switchWs(w.id)}
                            sx={{ px: 1.5, py: 0.3 }}>
              <WsDot color={w.color} />
              <Typography variant="body2" noWrap
                          sx={{ ml: 0.7, fontSize: 12.5 }}>
                {w.name}
              </Typography>
            </ListItemButton>)}
        </Box>
      </Panel>
      <Divider />
      <Webhooks project={project} open={panels.hooks}
                onToggle={() => togglePanel("hooks")} />
      <Deploy project={project} open={panels.deploy}
              onToggle={() => togglePanel("deploy")} />
      <Divider />
      <ListItemButton dense onClick={() => { setDrawerOpen(false);
                                             setBrowseOpen(true); }}
                      sx={{ px: 1.5 }}>
        <Typography variant="body2" sx={{ fontSize: 12.5 }}>
          🗂 Обзор репозиториев (GitHub/GitLab)
        </Typography>
      </ListItemButton>
      <ListItemButton dense onClick={() => { setDrawerOpen(false);
                                             setView("models"); }}
                      sx={{ px: 1.5 }}>
        <Typography variant="body2" sx={{ fontSize: 12.5 }}>
          🤖 Модели
        </Typography>
      </ListItemButton>
      <Box sx={{ px: 2, py: 1.5, display: "flex", flexDirection: "column",
                 gap: 1.5 }}>
        <Typography variant="caption" color="text.secondary">
          {statusText}
        </Typography>
      </Box>
    </Box>
  );

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <GlobalStyles styles={mdStyles} />
      <ErrBoundary>
      <Box sx={{ display: "flex", flexDirection: "column", minHeight: "100vh" }}>
        <AppBar position="fixed" color="primary"
                sx={{ bgcolor: accent }}>
          <Toolbar variant="dense" sx={{ gap: 1 }}>
            {projIcon
              ? (/^https?:|^\/\S/.test(projIcon)
                ? <img src={projIcon} alt="" style={{ height: 24,
                       width: 24, objectFit: "cover", borderRadius: 6 }} />
                : <Typography component="span" sx={{ fontSize: 20,
                       lineHeight: 1 }}>{projIcon}</Typography>)
              : <img src="/static/favicon.svg" alt=""
                     style={{ height: 24, filter: "invert(1)" }} />}
            <Typography variant="h6" sx={{ fontSize: 19, flexShrink: 0,
                                           display: "flex",
                                           alignItems: "center", gap: 0.8 }}>
              WebDev
              <Typography component="span" variant="caption"
                          sx={{ opacity: .55, fontSize: 11,
                       display: { xs: "none", sm: "inline" } }}>
                (v{status.version || "…"})
              </Typography>
              <ConnBadge conn={conn} showVer={false} />
            </Typography>
            {multiMode && (
              <Typography variant="body2" noWrap
                sx={{ opacity: .9, fontSize: 13, flexShrink: 0 }}>
                {project}
              </Typography>)}
            <Box sx={{ mr: "auto" }} />
            <Typography variant="body2"
              sx={{ display: { xs: "none", md: "block" }, opacity: .9,
                    fontSize: 13 }}>
              {statusText}
            </Typography>
            {status.current_task && (
              <Tooltip title="остановить текущую задачу">
                <Button size="small" variant="outlined" color="inherit"
                        onClick={() => setConfirm({ kind: "stop",
                          name: status.current_task })}
                        sx={{ borderColor: "rgba(255,255,255,.55)",
                              color: "#ffcdd2", fontSize: 11, px: 1,
                              whiteSpace: "nowrap" }}>
                  ⛔ Стоп
                </Button>
              </Tooltip>
            )}
            <ProxySel />
            <Tooltip title="профиль">
              <IconButton color="inherit"
                          onClick={e => setProfMenu(e.currentTarget)}>
                <PersonIcon />
              </IconButton>
            </Tooltip>
            <Menu anchorEl={profMenu} open={!!profMenu}
                  onClose={() => setProfMenu(null)}>
              {status.is_admin &&
                <MenuItem onClick={() => { setProfMenu(null);
                                           setUsersOpen(true); }}>
                  <PeopleIcon fontSize="small" sx={{ mr: 1 }} />
                  Пользователи
                </MenuItem>}
              <MenuItem onClick={() => { setProfMenu(null);
                                         setWsOpen(true); }}>
                <WorkspacesIcon fontSize="small" sx={{ mr: 1 }} />
                Рабочее пространство
              </MenuItem>
              <MenuItem onClick={() => { setProfMenu(null);
                                         setKeysOpen(true); }}>
                <KeyIcon fontSize="small" sx={{ mr: 1 }} />
                Ключи репозиториев
              </MenuItem>
              <MenuItem onClick={() => { setProfMenu(null);
                                         setSetOpen(true); }}>
                <SettingsIcon fontSize="small" sx={{ mr: 1 }} />
                Настройки
              </MenuItem>
              <MenuItem onClick={() => { setProfMenu(null);
                                         setProfileOpen(true); }}>
                <LockIcon fontSize="small" sx={{ mr: 1 }} />
                Смена пароля
              </MenuItem>
              <MenuItem onClick={logout}>
                <LogoutIcon fontSize="small" sx={{ mr: 1 }} />
                Выход
              </MenuItem>
            </Menu>
          </Toolbar>
        </AppBar>
        {/* spacer — AppBar is position:fixed, header stays pinned on top */}
        <Toolbar variant="dense" />
        {/* вкладки проектов — полоса под шапкой перед баром ветки;
            клик = перезагрузка страницы на выбранном проекте */}
        {multiMode && (
          <ProjectTabs projects={projects} tabs={tabs} current={project}
                       onTab={switchTab} onClose={closeTab}
                       onAdd={() => setAddOpen(true)}
                       wsmap={wsmap} wsList={wsInfo.ws}
                       onWs={(p, id) =>
                         post("/api/project/ws",
                              { project: p, ws: id })
                           .then(() => refreshProjects())}
                       onSettings={p => setPSetOpen(p)}
                       accent={accent} />)}

        {/* бар ветки: имя + коммит/пуш + новая ветка (xs — в 3 части) */}
        {brInfo?.current &&
          <Box sx={{ display: "flex", alignItems: "center",
                     gap: { xs: 0.5, md: 1 },
                     position: "sticky", top: 48, zIndex: 5,
                     height: 32, boxSizing: "border-box",
                     px: { xs: 0.8, md: 1.5 }, py: 0.3,
                     bgcolor: "background.paper",
                     borderBottom: "1px solid",
                     borderColor: "divider",
                     color: "text.secondary" }}>
            <AccountTreeIcon sx={{ fontSize: 14, flexShrink: 0 }} />
            <Typography component="span" variant="caption" noWrap
                        sx={{ flex: 1, minWidth: 0, fontSize: 11.5,
                              fontFamily:
                                "ui-monospace, Menlo, monospace" }}>
              {brInfo.current}
            </Typography>
            {(brInfo.branches || [])
              .find(b => b.current && b.dirty > 0) &&
              <Tooltip title="закоммитить незакоммиченные изменения и запушить">
                <Button size="small" variant="contained" color="success"
                        onClick={repoCommit}
                        sx={{ fontSize: { xs: 10, md: 11 },
                              px: { xs: 0.8, md: 1.5 }, py: 0,
                              height: { xs: 22, md: 24 },
                              whiteSpace: "nowrap", minWidth: 0 }}>
                  ✅ коммит+пуш</Button>
              </Tooltip>}
            <Tooltip title="переключить/создать ветку репозитория">
              <Button size="small" variant="outlined"
                      onClick={openBranchDlg}
                      sx={{ fontSize: { xs: 10, md: 11 },
                            px: { xs: 0.8, md: 1.5 }, py: 0,
                            height: { xs: 22, md: 24 },
                            whiteSpace: "nowrap", minWidth: 0 }}>
                🌿 ветка</Button>
            </Tooltip>
          </Box>}

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

        {/* десктоп: лента+сайдбар на всю ширину экрана — боковые
            отступы дают паддинги колонок (~12–16px от краёв) */}
        <Box sx={{ flex: 1, display: "flex", width: "100%",
                   minHeight: 0 }}>
          {view === "models"
            ? <ModelsPage accent={accent} toast={setToast}
                          onClose={() => setView("feed")} />
          : !project
            ? <Box sx={{ flex: 1, display: "flex",
                         alignItems: "center",
                         justifyContent: "center" }}>
                <Typography color="text.secondary" sx={{ fontSize: 15 }}>
                  Выберите проект — «+» слева вверху
                </Typography>
              </Box>
          : <>
          <Box sx={{ flex: 1, minWidth: 0, minHeight: 0,
                     display: "flex", flexDirection: "column",
                     p: { xs: "8px 2px", md: "16px 12px 0" },
                     // запас снизу = высота фиксированного композера +
                     // зазор, равный верхнему отступу — колонки
                     // заканчиваются ровно над баром
                     pb: { xs: compH + 8 + "px",
                           md: compH + 16 + "px" } }}>
            {/* канбан-доска: каждая тема — колонка со своими задачами,
                листается влево-вправо (на мобильной — со снапом);
                «целевая» колонка (клик по заголовку) — куда падают
                новые задачи из композера */}
            <Box sx={{ display: "flex", gap: 1.2, alignItems: "stretch",
                       overflowX: "auto",
                       px: { xs: 0.6, md: 0 },
                       // доска занимает ровно оставшуюся высоту
                       // (flex-раскладка вместо жёсткого calc —
                       // страница не скроллится, низ колонок
                       // прилегает к композеру)
                       flex: 1, minHeight: 0,
                       scrollSnapType: { xs: "x proximity", md: "none" },
                       "&::-webkit-scrollbar": { height: 8 } }}>
              {/* доска = «Главная» + темы в общем порядке (sort);
                  главная — такая же колонка: двигается, но не
                  удаляется */}
              {(() => {
                return boardCols.map((c, ci) => {
                  const mvL = ci > 0
                    ? () => moveTopic(c.key, "left") : null;
                  const mvR = ci < boardCols.length - 1
                    ? () => moveTopic(c.key, "right") : null;
                  if (c.key === "main")
                    return (
                      <TopicColumn key="main" sess={false}
                        name={c.name}
                        count={mainItems.length}
                        sel={topicSel === "main"}
                        accent={accent} color={mainDef.color}
                        tset={mainDef} eff={mainDef.eff}
                        onSelect={() => selectTopic("main")}
                        onNewTask={() => newTaskIn("main")}
                        onDict={() => toggleDictCol("main",
                          mainDef.eff?.reply_mode)}
                        dictOn={dict?.kind === "col"
                                && dict?.key === "main"}
                        onStats={() => setStatDlg(
                          { key: "main",
                            name: "⭐ " + (mainDef.name
                                          || "Главная") })}
                        onSettings={() => setTSetDlg(
                          { kind: "main", current: mainDef })}
                        onMoveL={mvL} onMoveR={mvR}
                        more={colMore.main} busy={!!colBusy.main}
                        onMore={() => loadColMore("main")}
                        onBodyOver={e => overCol(e, "main")}
                        onBodyDrop={e => dropCol(e, "main")}
                        empty={!items.length
                          ? "Задач пока нет — напиши первую внизу."
                          : "нет задач"}
                        loading={!booted}
                        pending={pendSet.has("col:main")}>
                        {colCards(mainItems, "main")}
                      </TopicColumn>);
                  const tp = topics.find(
                    t => String(t.id) === c.key);
                  if (!tp) return null;
                  return (
                    <TopicColumn key={tp.id}
                      name={tp.name || `тема #${tp.id}`}
                      sess={tp.has_session}
                      count={byTopic(tp.id).length}
                      sel={topicSel === String(tp.id)} accent={accent}
                      color={tp.color} tset={tp} eff={tp.eff}
                      onSelect={() => selectTopic(String(tp.id))}
                      onNewTask={() => newTaskIn(String(tp.id))}
                      onDict={() => toggleDictCol(String(tp.id),
                        tp.eff?.reply_mode)}
                      dictOn={dict?.kind === "col"
                              && dict?.key === String(tp.id)}
                      onStats={() => setStatDlg(
                        { key: String(tp.id),
                          name: tp.name || `тема #${tp.id}` })}
                      more={colMore[String(tp.id)]}
                      busy={!!colBusy[String(tp.id)]}
                      onMore={() => loadColMore(String(tp.id))}
                      onSettings={() => setTSetDlg(
                        { kind: "edit", topic: tp })}
                      onMoveL={mvL} onMoveR={mvR}
                      onDelete={() =>
                        askDelTopic(tp.id, tp.name || `тема #${tp.id}`)}
                      onBodyOver={e => overCol(e, String(tp.id))}
                      onBodyDrop={e => dropCol(e, String(tp.id))}
                      loading={!booted}
                      pending={pendSet.has("col:" + tp.id)}>
                      {colCards(byTopic(tp.id), String(tp.id))}
                    </TopicColumn>);
                });
              })()}
              {/* задачи темы, которой ещё нет в списке (гонка опроса)
                  — временная колонка без меню */}
              {orphanTids.map(tid =>
                <TopicColumn key={"t" + tid}
                  name={"тема #" + tid} sess={false}
                  count={byTopic(tid).length}
                  sel={topicSel === String(tid)} accent={accent}
                  onSelect={() => selectTopic(String(tid))}
                  onNewTask={() => newTaskIn(String(tid))}
                  onDict={() => toggleDictCol(String(tid))}
                  dictOn={dict?.kind === "col"
                          && dict?.key === String(tid)}
                  onStats={() => setStatDlg(
                    { key: String(tid), name: "тема #" + tid })}
                  more={colMore[String(tid)]}
                  busy={!!colBusy[String(tid)]}
                  onMore={() => loadColMore(String(tid))}
                  onBodyOver={e => overCol(e, String(tid))}
                  onBodyDrop={e => dropCol(e, String(tid))}
                  loading={!booted}>
                  {colCards(byTopic(tid), String(tid))}
                </TopicColumn>)}
              {project && project !== "workspace" &&
                <Paper variant="outlined" onClick={createTopic}
                       sx={{ width: { xs: "55vw", sm: 190 },
                             flexShrink: 0, scrollSnapAlign: "start",
                             alignSelf: "flex-start",
                             borderRadius: "12px", cursor: "pointer",
                             borderStyle: "dashed", borderColor: "divider",
                             "&:hover": { borderColor:
                               accent || "primary.main" } }}>
                  <Tooltip title="новая тема — первая задача стартует свою сессию Devin">
                    <Box sx={{ px: 1.1, py: 0.8, display: "flex",
                               alignItems: "center", gap: 0.6 }}>
                      <Typography sx={{ fontSize: 13, fontWeight: 600,
                                        color: accent || "primary.main" }}>
                        ＋ Новая тема
                      </Typography>
                    </Box>
                  </Tooltip>
                </Paper>}
            </Box>
          </Box>
          {/* сайдбар жёстко прижат: от хедера до низа экрана, скроллит
              внутри один общий список; block-layout — секции не сжимаются
              и не наезжают друг на друга при длинных списках */}
          <Paper elevation={0} sx={{
            width: 290, flexShrink: 0, m: "0 12px 0 4px",
            display: { xs: "none", md: "block" },
            // высота — по ряду (низ экрана), своего calc нет:
            // скроллится список внутри, страница — никогда
            alignSelf: "stretch",
            borderRadius: "14px",
            border: "1px solid", borderColor: "divider",
            overflowY: "auto", overflowX: "hidden",
            // pb как у ленты: нижние пункты докручиваются выше
            // фиксированного композера (иначе уходят под него)
            pb: "150px" }}>
            <Instr project={project} open={panels.instr}
                   onToggle={() => togglePanel("instr")}
                   toast={setToast} />
            <Divider />
            <Panel title="Файлы проекта" open={panels.files}
                   onToggle={() => togglePanel("files")}
                   icon={<FolderOpenIcon sx={{ fontSize: 16, ml: 0.5 }} />}
                   right={
                     <Tooltip title="обновить список файлов">
                       <IconButton size="small"
                                   onClick={() => setTreeVer(v => v + 1)}>
                         <RefreshIcon sx={{ fontSize: 16 }} />
                       </IconButton>
                     </Tooltip>}>
              <Box sx={{ px: 1 }}>
                <FileTree key={project + ":" + treeVer}
                          project={project} onError={setToast}
                          onOpenFile={setEditPath} />
              </Box>
            </Panel>
            <Divider />
            <Changes project={project} toast={setToast}
                     open={panels.changes}
                     onToggle={() => togglePanel("changes")}
                     bOpen={panels.builds}
                     onToggleB={() => togglePanel("builds")} />
            <Divider />
            <Branches project={project} open={panels.branches}
                      onToggle={() => togglePanel("branches")}
                      toast={setToast} />
            <Divider />
            <Panel title="Пространства" open={panels.ws}
                   onToggle={() => togglePanel("ws")}
                   icon={<WorkspacesIcon sx={{ fontSize: 16, ml: 0.5 }} />}
                   chip={<Box sx={{ ml: 1, width: 18, height: 18,
                                         borderRadius: "50%", bgcolor: wsColor,
                                         color: "#fff", fontSize: 11,
                                         fontWeight: 600, display: "flex",
                                         alignItems: "center",
                                         justifyContent: "center" }}>
                                   {wsInfo.ws.length}
                                 </Box>}>
              <Box>
                {wsInfo.ws.map(w =>
                  <ListItemButton key={w.id} dense
                                        selected={w.id === wsInfo.active}
                                        onClick={() =>
                                          w.id !== wsInfo.active && switchWs(w.id)}
                                        sx={{ px: 1.5, py: 0.3 }}>
                    <WsDot color={w.color} />
                    <Typography variant="body2" noWrap
                                      sx={{ ml: 0.7, fontSize: 12.5 }}>
                      {w.name}
                    </Typography>
                  </ListItemButton>)}
              </Box>
            </Panel>
      <Divider />
            <Webhooks project={project} open={panels.hooks}
                      onToggle={() => togglePanel("hooks")} />
            <Deploy project={project} open={panels.deploy}
                    onToggle={() => togglePanel("deploy")} />
            <Divider />
            <ListItemButton dense onClick={() => setBrowseOpen(true)}
                            sx={{ px: 1.5 }}>
              <Typography variant="body2" sx={{ fontSize: 12.5 }}>
                🗂 Обзор репозиториев (GitHub/GitLab)
              </Typography>
            </ListItemButton>
            <ListItemButton dense onClick={() => setView("models")}
                            sx={{ px: 1.5 }}>
              <Typography variant="body2" sx={{ fontSize: 12.5 }}>
                🤖 Модели
              </Typography>
            </ListItemButton>
          </Paper>
          </>}
        </Box>

        {project && <Composer project={project} sttStatus={status.stt_status}
                  inject={compInj}
                  toast={setToast} onSent={loadTasks} accent={accent}
                  note={noteSel ? feed.get(noteSel) : null}
                  onNoteDone={() => setNoteSel(null)}
                  cont={contSel ? feed.get(contSel) : null}
                  onContDone={() => setContSel(null)}
                  topic={topicSel} topicName={topicName} topics={topics}
                  mainDef={mainDef}
                  onTopic={selectTopic} onNewTopic={createTopic}
                  conn={conn} onOpenDrawer={() => setDrawerOpen(true)}
                  mode={mode}
                  fast={effFast} fastOv={fastOv !== null}
                  onFast={toggleFast}
                  onMode={m => post("/api/project/settings",
                      { project, reply_mode: m }).then(d => {
                    setToast(d.ok
                      ? (m === "ask" ? "Режим: ответ на вопрос"
                                     : "Режим: код")
                      : "Ошибка: " + (d.error || "?"));
                    if (d.ok) setMode(m);
                  }).catch(() => setToast("Сеть: не сохранил режим"))} />}

      {dict && (
        <Paper elevation={0} sx={{
          position: "fixed", left: "50%", transform: "translateX(-50%)",
          bottom: { xs: 150, md: 130 }, zIndex: 30, px: 1.6, py: 0.7,
          borderRadius: "12px", display: "flex", alignItems: "center",
          gap: 1, border: "1px solid", borderColor: "divider",
          boxShadow: "0 8px 24px rgba(28,33,40,.14)" }}>
          <Box sx={{ width: 9, height: 9, borderRadius: "50%",
                     bgcolor: "error.main",
                     animation: "blink 1s ease-in-out infinite",
                     "@keyframes blink": { "50%": { opacity: .25 } } }} />
          <Typography variant="body2" sx={{ fontSize: 13 }}>
            {dictInfo || "00:00"} — {dict.kind === "note"
              ? "диктую в заметку" : "диктую в колонку"}
          </Typography>
          <Button size="small" color="error" onClick={stopDict}
                  sx={{ textTransform: "none", fontSize: 12 }}>
            ■ стоп
          </Button>
        </Paper>)}
      </Box>

      <TopicStatsDlg dlg={statDlg} project={project}
                     onClose={() => setStatDlg(null)}
                     toast={setToast} />
      <TopicSettings project={project} dlg={tSetDlg} topics={topics}
                     onClose={() => setTSetDlg(null)}
                     onSaved={id => { loadTasks();
                       if (id) selectTopic(String(id)); }}
                     toast={setToast} />
      <FileEditor project={project} path={editPath}
                  onClose={() => setEditPath(null)} toast={setToast} />
      <Settings open={setOpen} onClose={() => setSetOpen(false)}
                onChanged={refreshProjects} />
      <RepoKeys open={keysOpen}
                onClose={() => { setKeysOpen(false);
                                 if (!multiMode) setAddOpen(true); }} />
      <ProjectSettings project={pSetOpen}
                       onClose={saved => {
                         setPSetOpen(null);
                         if (saved !== true) setColorPreview(null);
                         loadProjSettings(); }}
                       onPreview={setColorPreview}
                       onDeleted={refreshProjects}
                       toast={setToast} />
      <Workspaces open={wsOpen} onClose={() => setWsOpen(false)}
                  onChanged={() => { loadWs(); refreshProjects(); }} />
      <Users open={usersOpen} onClose={() => setUsersOpen(false)}
             me={status.user} />
      <RepoBrowse open={browseOpen} onClose={() => setBrowseOpen(false)}
        onAdd={r => { setBrowseOpen(false);
                      setAddPreset({ url: r.url,
                        folder: (r.name || "").split("/").pop() });
                      setAddOpen(true); }} />
      <AddProject open={addOpen} onClose={() => setAddOpen(false)}
                  preset={addPreset}
                  wsList={wsInfo.ws} wsActive={wsInfo.active}
                  onAdded={f => { refreshProjects()
                    .then(() => selectProject(f)); }} />


      <Dialog open={!!confirm} onClose={() => setConfirm(null)}
              maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontSize: 16 }}>
          {confirm?.kind === "stop" ? "Остановить задачу?"
           : confirm?.kind === "del" ? "Удалить задачу?"
           : confirm?.kind === "topic_del" ? "Удалить тему?"
                                   : "Удалить задачу из очереди?"}
        </DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            {confirm?.kind === "stop"
              ? `«${confirm.name}» будет принудительно убита — воркер ` +
                "возьмёт следующую из очереди. Незакоммиченные изменения " +
                "в репо останутся."
              : confirm?.kind === "del"
              ? `«${confirm?.name}» будет удалена безвозвратно вместе ` +
                "с выводом и статистикой."
              : confirm?.kind === "topic_del"
              ? (confirm?.active?.length
                ? `Удалить нельзя — в теме «${confirm.name}» ` +
                  `выполняется или ждёт очереди задача: ` +
                  `${confirm.active.slice(0, 3).join(", ")}` +
                  (confirm.active.length > 3
                    ? ` и ещё ${confirm.active.length - 3}` : "") +
                  `. Повторите после её завершения.`
                : `Тема «${confirm?.name}»` +
                  (confirm?.cards
                    ? ` и её карточки (${confirm.cards} шт.)` : "") +
                  " будут удалены безвозвратно.")
              : `«${confirm?.name}» будет удалена из очереди и не ` +
                "выполнится. Действие необратимо."}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirm(null)}>Отмена</Button>
          <Button color="error" variant="contained" onClick={confirmAct}
            disabled={confirm?.kind === "topic_del" &&
                      (confirm?.active || []).length > 0}>
            {confirm?.kind === "stop" ? "Остановить" : "Удалить"}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!branchDlg} onClose={() => setBranchDlg(null)}
              fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontSize: 16 }}>Новая ветка</DialogTitle>
        <DialogContent>
          <Typography variant="caption" color="text.secondary">
            Создаст ветку от текущей и сразу переключится на неё.
          </Typography>
          <TextField autoFocus fullWidth size="small" label="Имя ветки"
                     value={branchName}
                     onChange={e => setBranchName(e.target.value)}
                     sx={{ mt: 1.5 }} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBranchDlg(null)}>Отмена</Button>
          <Button variant="contained" disabled={!branchName.trim()}
            onClick={async () => {
              const name = branchName.trim();
              setBranchDlg(null);
              const d = await post("/api/branch/new",
                                   { project: projRef.current, name });
              setToast(d.ok ? "Ветка создана: " + name
                            : "Ошибка: " + (d.error || "?"));
              if (d.ok) loadBranches();
            }}>
            Создать и перейти</Button>
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
