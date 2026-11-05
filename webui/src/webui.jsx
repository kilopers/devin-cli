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
  ListSubheader, Menu, MenuItem, Paper, Select, Snackbar, SwipeableDrawer,
  TextField, Toolbar, Tooltip, Typography,
} from "@mui/material";
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
import ArticleIcon from "@mui/icons-material/Article";
import DeleteOutlinedIcon from "@mui/icons-material/DeleteOutlined";
import ReplayIcon from "@mui/icons-material/Replay";
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

const TaskCard = React.memo(function TaskCard({ t, onStop, onCancel,
                                               onDel, toast, hideTopic,
                                               sel, onNote }) {
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
  // живая консоль прилипает к низу на каждом обновлении хвоста
  useEffect(() => {
    const el = outRef.current;
    if (outOpen && el && t.status !== "done")
      el.scrollTop = el.scrollHeight;
  }, [t.output, outOpen]);
  const succeeded = t.status === "done" &&
    !(t.task_status && !/exit code: 0/.test(t.task_status));
  // «в работу»: у задачи-вопроса (reply_mode=ask) из модалки 📄 тот
  // же промпт уходит обычной code-задачей в ту же тему. Кнопку
  // подсвечиваем, когда в ответе Devin есть предложение реализации
  // («если хочешь — сделаем» и т.п.)
  const [workBusy, setWorkBusy] = useState(false);
  const offersWork = t.mode === "ask" && succeeded &&
    /если хочешь|могу (сделать|реализовать|добавить|исправить|помочь)|скажи[^\n.]{0,30}сделаю|давай сделаем|готов (сделать|реализовать)|предлагаю|shall i|could implement|can implement/i
      .test(t.output || "");
  const sendToWork = async () => {
    if (workBusy) return;
    let text = promptShown || "";
    if (full === null && maybeCut) {
      try {
        const d = await apiJson("/api/task/" + t.stem + "/prompt");
        if (d.ok) { setFull(d.prompt); text = d.prompt; }
      } catch { /* сеть — отправим что есть */ }
    }
    if (!text.trim()) return;
    setWorkBusy(true);
    try {
      // один и тот же вопрос голым текстом Devin снова читает как
      // вопрос — добавляем указание реализовать его предложение
      const body = {
        text: "Давай сделаем по твоему предложению из предыдущего "
              + "ответа — реализуй его.\n\nИсходный вопрос:\n" + text,
        mode: "code" };
      if (t.project) body.project = t.project;
      if (t.tid) body.topic = String(t.tid);
      // скрыто подмешиваем сам ответ Devin (его предложение) в
      // инструкции задачи — новая сессия уже знает, что реализовать;
      // на карточке этот текст не светится
      if ((t.output || "").trim())
        body.instr = "## Результат предыдущего ответа Devin\n" +
                     t.output.trim().slice(0, 6000);
      const d = await post("/api/tasks", body);
      if (d.ok) { toast?.("Отправлено в работу"); setOutOpen(false); }
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
      const d = await post("/api/tasks", body);
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
    ["Стоимость", costStr],
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
  // дописывает текст в неё; «▶ начать выполнение» ставит её в
  // очередь с настройками своей колонки
  const isNote = t.status === "note";
  const [runBusy, setRunBusy] = useState(false);
  // лоадер держим до смены статуса (поллинг привезёт 'queued') —
  // иначе кнопка успевает «моргнуть» обратно в «начать выполнение»
  useEffect(() => {
    if (t.status !== "note") setRunBusy(false);
  }, [t.status]);
  const runNote = async () => {
    if (runBusy) return;
    setRunBusy(true);
    try {
      const d = await post("/api/task/run", { stem: t.stem });
      if (d.ok) {
        toast?.("▶ Заметка отправлена в работу");
        if (sel) onNote?.(t);   // ушла в очередь — отжать выбор
        return;                 // busy сбросится эффектом выше
      }
      toast?.("Ошибка: " + (d.error || "?"));
    } catch (e) { toast?.("Сеть: " + e); }
    setRunBusy(false);
  };
  // мелкие мета-чипы шапки: один стиль, воздух вокруг текста
  const metaSx = { height: 22, fontSize: 11, fontWeight: 500,
                   borderRadius: "7px",
                   "& .MuiChip-label": { px: "8px" } };
  // чипы настроек — только когда значение отличается от дефолта
  // колонки (ov из /api/tasks); у старых записей без ov — показываем
  const ov = t.ov || { mode: true, model: true, ac: true };
  return (
    <Card elevation={0}
      onClick={isNote ? () => onNote?.(t) : undefined}
      sx={{
      mb: 1.6, borderRadius: "14px",
      border: "1px solid", borderColor: "divider",
      cursor: isNote ? "pointer" : "default",
      transition: "box-shadow .2s ease, border-color .2s ease",
      ...(sel && { borderColor: "#5e6ad2",
                   bgcolor: "rgba(94,106,210,.05)",
                   boxShadow: "0 0 0 1px #5e6ad2" }),
      "&:hover": { borderColor: sel ? "#5e6ad2" : "#c9cfda",
                   boxShadow: sel ? "0 0 0 1px #5e6ad2"
                                  : "0 4px 18px rgba(16,24,40,.07)" } }}>
      <CardContent sx={{ p: "14px 20px 10px",
                         "&:last-child": { pb: "10px" } }}>
        <Box sx={{ display: "flex", justifyContent: "space-between",
                   alignItems: "flex-start", gap: 1.5,
                   flexWrap: "wrap", mb: 1.2 }}>
          <Box sx={{ display: "flex", alignItems: "center",
                     gap: 0.8, flexWrap: "wrap", minWidth: 0 }}>
            <Typography variant="caption" color="text.secondary"
                        sx={{ fontSize: 12, mr: 0.2 }}>
              {new Date(t.created * 1000).toLocaleString("ru-RU")}
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
            {isNote && onDel && (
              <Tooltip title="удалить заметку">
                <IconButton size="small" onClick={() => onDel(t)}
                  sx={{ p: "3px", color: "error.main" }}>
                  <DeleteOutlinedIcon sx={{ fontSize: 15 }} />
                </IconButton>
              </Tooltip>
            )}
            <Tooltip title={isNote ? "текст заметки"
                          : succeeded ? "результат задачи"
                                      : "вывод задачи"}>
              <IconButton size="small" onClick={() => setOutOpen(true)}
                sx={{ p: "3px", color: "text.secondary" }}>
                <ArticleIcon sx={{ fontSize: 15 }} />
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
            {t.status === "done" && !succeeded && (
              <Tooltip title="повторить задачу — в очередь с теми же параметрами, старая запись удалится">
                <IconButton size="small" onClick={retry}
                  disabled={retryBusy}
                  sx={{ p: "3px", color: "text.secondary" }}>
                  <ReplayIcon sx={{ fontSize: 15 }} />
                </IconButton>
              </Tooltip>
            )}
            {t.status === "done" && !succeeded && onDel && (
              <Tooltip title="удалить задачу">
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
            {isNote
              ? <Tooltip title="отправить в работу с настройками её колонки">
                  <Button size="small" variant="outlined"
                          onClick={runNote} disabled={runBusy}
                          startIcon={runBusy
                            ? <Box component="span" sx={{
                                width: 11, height: 11,
                                border: "2px solid #5e6ad2",
                                borderTopColor: "transparent",
                                borderRadius: "50%",
                                animation: "rot .8s linear infinite",
                                "@keyframes rot":
                                  { to: { transform:
                                          "rotate(360deg)" } } }} />
                            : undefined}
                          sx={{ fontSize: 11, px: 1.2, height: 26,
                                borderRadius: "7px", whiteSpace: "nowrap",
                                textTransform: "none" }}>
                    {runBusy ? "запускаю…" : "▶ начать выполнение"}
                  </Button>
                </Tooltip>
              : <StatusChip t={t} />}
          </Box>
        </Box>
        <Typography variant="body2" ref={txtRef}
          onClick={!isNote && (canExpand || open)
                   ? () => setOpen(o => !o) : undefined}
          sx={{ whiteSpace: "pre-wrap", fontWeight: 500, fontSize: 13.5,
                lineHeight: 1.62,
                cursor: !isNote && (canExpand || open) ? "pointer"
                                                       : "inherit",
                ...(!open && {
                  display: "-webkit-box", WebkitBoxOrient: "vertical",
                  WebkitLineClamp: 3, overflow: "hidden" }) }}>
          {promptShown}</Typography>
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
            <Typography variant="caption" color="text.secondary"
                        sx={{ fontFamily: MONO, fontSize: 11.5,
                              wordBreak: "break-all" }}>
              {t.name}
            </Typography>
            <Box sx={{ mt: 1 }}>
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
        <Dialog open={outOpen} onClose={() => setOutOpen(false)}
                maxWidth="md" fullWidth slotProps={dlgSlotProps}>
          <DialogTitle sx={{ fontSize: 15, fontWeight: 600, pr: 6 }}>
            {isNote ? "Заметка"
                   : succeeded ? "Результат задачи" : "Вывод задачи"}
            {t.mode === "ask" && t.status === "done" && (
              <Tooltip title="создать code-задачу по предложению из ответа">
                <span>
                  <Button size="small"
                          variant={offersWork ? "contained" : "outlined"}
                          onClick={sendToWork} disabled={workBusy}
                          sx={{ ml: 1.2, fontSize: 11.5, px: 1.2, py: 0.1,
                                textTransform: "none",
                                whiteSpace: "nowrap" }}>
                    {workBusy ? "отправляю…" : "▶ в работу"}
                  </Button>
                </span>
              </Tooltip>)}
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
            <Typography variant="caption" color="text.secondary"
                        sx={{ fontFamily: MONO, fontSize: 11.5,
                              wordBreak: "break-all" }}>
              {t.name}
            </Typography>
            <Box sx={{ mt: 1 }}>
              {isNote
                ? <Markdown text={promptShown} />
                : t.status === "done"
                ? (t.output
                    ? <Markdown text={t.output} />
                    : <Typography variant="body2" color="text.secondary">
                        вывод пуст — Devin ничего не вернул</Typography>)
                : (t.output
                    ? <pre className="out" ref={outRef}
                           style={{ maxHeight: "60vh" }}>{t.output}</pre>
                    : <Typography variant="body2" color="text.secondary">
                        {t.status === "queued"
                          ? "в очереди — вывод ещё пуст"
                          : "вывод пока пуст"}</Typography>)}
            </Box>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
});

// Project picker in the header — replaces the old tabs row; selection
// persists server-side via POST /api/project (kv.project_web).
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
                      empty, children, more, busy, onMore }) {
  const [menu, setMenu] = useState(null);
  return (
    <Paper variant="outlined" sx={{
      width: { xs: "82vw", sm: 300, md: 320 }, flexShrink: 0,
      borderRadius: "12px", scrollSnapAlign: "start",
      borderColor: sel ? (boostColor(color) || accent || "primary.main")
                       : "divider",
      borderWidth: sel ? 2 : 1,
      bgcolor: color || "background.paper" }}>
      <Box onClick={onSelect}
           sx={{ display: "flex", alignItems: "center", gap: 0.6,
                 px: 1.1, py: 0.7, cursor: "pointer",
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
        {(onDelete || onSettings || onMoveL || onMoveR) &&
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
              {onSettings &&
                <MenuItem dense sx={{ fontSize: 13 }}
                  onClick={() => { setMenu(null); onSettings(); }}>
                  ⚙ Настройки
                </MenuItem>}
              {onMoveL &&
                <MenuItem dense sx={{ fontSize: 13 }}
                  onClick={() => { setMenu(null); onMoveL(); }}>
                  ◀ Сместить влево
                </MenuItem>}
              {onMoveR &&
                <MenuItem dense sx={{ fontSize: 13 }}
                  onClick={() => { setMenu(null); onMoveR(); }}>
                  ▶ Сместить вправо
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
                   px: 0.9, py: 0.5,
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
            [eff.reply_mode === "ask" ? "💬 спросить" : "🛠 код",
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
      <Box sx={{ p: 0.8, display: "flex", flexDirection: "column",
                 gap: 0.8 }}>
        <Button size="small" fullWidth onClick={onNewTask}
                sx={{ textTransform: "none", fontSize: 12, py: 0.3,
                      color: "text.secondary", border: "1px dashed",
                      borderColor: "divider", borderRadius: "8px" }}>
          ＋ задача сюда
        </Button>
        {children}
        {!React.Children.count(children) &&
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
  // список тем текущего проекта уже загружен — можно проверять,
  // не удалили ли сохранённую тему
  const topicsLoaded = useRef(false);
  const [feed, setFeed] = useState(new Map());
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

  // свежие сверху: в колонках новые задачи первыми
  const items = useMemo(() =>
    [...feed.values()].sort((a, b) => b.created - a.created), [feed]);
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
          setTopics(td.topics || []);
          setMainDef(td.main || {});
          tkeys = ["main",
            ...(td.topics || []).map(t => String(t.id))];
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
    setNoteSel(null);
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
    post("/api/topics", { action: "move", project: projRef.current,
                          id, dir })
      .then(async d => {
        if (!d.ok) return setToast("Тема: " + (d.error || "?"));
        const td = await apiJson("/api/topics?project=" +
          encodeURIComponent(projRef.current)).catch(() => null);
        if (td?.ok) { setTopics(td.topics || []);
                      setMainDef(td.main || {}); }
      })
      .catch(() => setToast("Сеть: не сдвинул тему"));
  const askDelTopic = (id, name) =>
    setConfirm({ kind: "topic_del", tid: id, name });
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
  const toggleNote = useCallback(
    t2 => setNoteSel(s => s === t2.stem ? null : t2.stem), []);
  // карточку запустили/удалили — она перестала быть заметкой:
  // выбор снимаем, композер возвращается в обычный режим
  useEffect(() => {
    if (noteSel && feed.get(noteSel)?.status !== "note")
      setNoteSel(null);
  }, [feed, noteSel]);
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
    try {
      const d = c.kind === "stop"
        ? await post("/api/stop", { stem: confirm.stem })
        : c.kind === "del"
        ? await post("/api/task/delete", { stem: c.stem })
        : c.kind === "topic_del"
        ? await post("/api/topics", { action: "delete",
                       project: projRef.current, id: c.tid })
        : await post("/api/task/cancel", { stem: c.stem });
      if (d.ok) {
        setToast(c.kind === "stop" ? "⛔ Остановлено: " + d.stopped
                 : c.kind === "del" ? "🗑 Задача удалена"
                 : c.kind === "topic_del" ? "🗑 Тема удалена"
                                   : "Удалено из очереди: " + c.name);
        if (c.kind === "cancel" || c.kind === "del")
          setFeed(m => { const n = new Map(m); n.delete(c.stem); return n; });
        if (c.kind === "topic_del") {
          setTopics(ts => ts.filter(t => t.id !== c.tid));
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
              <ProjectSelect projects={projects} current={project}
                             onChange={selectProject}
                             onAdd={() => setAddOpen(true)}
                             wsmap={wsmap} wsList={wsInfo.ws}
                             onWs={(p, id) =>
                               post("/api/project/ws",
                                    { project: p, ws: id })
                                 .then(() => refreshProjects())}
                             onSettings={p => setPSetOpen(p)} />
            )}
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
        <Box sx={{ flex: 1, display: "flex", width: "100%" }}>
          {view === "models"
            ? <ModelsPage accent={accent} toast={setToast}
                          onClose={() => setView("feed")} />
          : <>
          <Box sx={{ flex: 1, minWidth: 0,
                     p: { xs: "8px 2px 150px", md: "16px 12px 150px" } }}>
            {/* канбан-доска: каждая тема — колонка со своими задачами,
                листается влево-вправо (на мобильной — со снапом);
                «целевая» колонка (клик по заголовку) — куда падают
                новые задачи из композера */}
            <Box sx={{ display: "flex", gap: 1.2, alignItems: "flex-start",
                       overflowX: "auto", pb: 1.2,
                       px: { xs: 0.6, md: 0 },
                       scrollSnapType: { xs: "x proximity", md: "none" },
                       "&::-webkit-scrollbar": { height: 8 } }}>
              <TopicColumn sess={false}
                name={mainDef.name ? "⭐ " + mainDef.name
                                   : "⭐ Главная"}
                count={mainItems.length} sel={topicSel === "main"}
                accent={accent} color={mainDef.color}
                tset={mainDef} eff={mainDef.eff}
                onSelect={() => selectTopic("main")}
                onNewTask={() => newTaskIn("main")}
                onSettings={() => setTSetDlg(
                  { kind: "main", current: mainDef })}
                more={colMore.main} busy={!!colBusy.main}
                onMore={() => loadColMore("main")}
                empty={!items.length
                  ? "Задач пока нет — напиши первую внизу."
                  : "нет задач"}>
                {mainItems.map(t =>
                  <TaskCard key={t.stem} t={t} hideTopic
                            sel={noteSel === t.stem} onNote={toggleNote}
                            onStop={askStop} onCancel={askCancel}
                            onDel={askDel} toast={setToast} />)}
              </TopicColumn>
              {topics.map((tp, ti) =>
                <TopicColumn key={tp.id}
                  name={tp.name || `тема #${tp.id}`}
                  sess={tp.has_session}
                  count={byTopic(tp.id).length}
                  sel={topicSel === String(tp.id)} accent={accent}
                  color={tp.color} tset={tp} eff={tp.eff}
                  onSelect={() => selectTopic(String(tp.id))}
                  onNewTask={() => newTaskIn(String(tp.id))}
                  more={colMore[String(tp.id)]}
                  busy={!!colBusy[String(tp.id)]}
                  onMore={() => loadColMore(String(tp.id))}
                  onSettings={() => setTSetDlg(
                    { kind: "edit", topic: tp })}
                  onMoveL={ti > 0
                    ? () => moveTopic(tp.id, "left") : null}
                  onMoveR={ti < topics.length - 1
                    ? () => moveTopic(tp.id, "right") : null}
                  onDelete={() =>
                    askDelTopic(tp.id, tp.name || `тема #${tp.id}`)}>
                  {byTopic(tp.id).map(t =>
                    <TaskCard key={t.stem} t={t} hideTopic
                              sel={noteSel === t.stem} onNote={toggleNote}
                              onStop={askStop} onCancel={askCancel}
                              onDel={askDel} toast={setToast} />)}
                </TopicColumn>)}
              {/* задачи темы, которой ещё нет в списке (гонка опроса)
                  — временная колонка без меню */}
              {orphanTids.map(tid =>
                <TopicColumn key={"t" + tid}
                  name={"тема #" + tid} sess={false}
                  count={byTopic(tid).length}
                  sel={topicSel === String(tid)} accent={accent}
                  onSelect={() => selectTopic(String(tid))}
                  onNewTask={() => newTaskIn(String(tid))}
                  more={colMore[String(tid)]}
                  busy={!!colBusy[String(tid)]}
                  onMore={() => loadColMore(String(tid))}>
                  {byTopic(tid).map(t =>
                    <TaskCard key={t.stem} t={t} hideTopic
                              sel={noteSel === t.stem} onNote={toggleNote}
                              onStop={askStop} onCancel={askCancel}
                              onDel={askDel} toast={setToast} />)}
                </TopicColumn>)}
              {project && project !== "workspace" &&
                <Paper variant="outlined" onClick={createTopic}
                       sx={{ width: { xs: "55vw", sm: 190 },
                             flexShrink: 0, scrollSnapAlign: "start",
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
            alignSelf: "flex-start", position: "sticky", top: 80,
            height: "calc(100vh - 80px)", borderRadius: "14px",
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

        <Composer project={project} sttStatus={status.stt_status}
                  toast={setToast} onSent={loadTasks} accent={accent}
                  note={noteSel ? feed.get(noteSel) : null}
                  onNoteDone={() => setNoteSel(null)}
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
                  }).catch(() => setToast("Сеть: не сохранил режим"))} />
      </Box>

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
              ? `Тема «${confirm?.name}» будет удалена — её задачи ` +
                "вернутся в «Главную»."
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
