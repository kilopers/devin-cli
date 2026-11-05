// Страница «Модели» — отдельный экран (не модалка): при открытии
// синхронно запрашивает у devin свежий список (GET /api/models?fresh=1).
// Модели сгруппированы по family — заголовок группы раскрывается
// slide-down (Collapse) и показывает варианты со всей информацией.
import { useEffect, useState } from "react";
import {
  AppBar, Box, Card, CardContent, Chip, CircularProgress, Collapse,
  IconButton, ListItemButton, MenuItem, Radio, TextField, Toolbar,
  Tooltip, Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import MoneyOffIcon from "@mui/icons-material/MoneyOff";
import { apiJson, post } from "./api.js";

const ModelCard = ({ m, current, onPick }) => (
  <Card variant="outlined" onClick={() => onPick(m.id)}
        sx={{ mb: 1, cursor: "pointer" }}>
    <CardContent sx={{ py: 1, "&:last-child": { pb: 1 } }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        <Radio size="small" checked={m.id === current} sx={{ p: 0.5 }} />
        <Typography sx={{ fontFamily: "monospace", fontWeight: 600,
                          fontSize: 14 }}>{m.id}</Typography>
        {m.info?.label && m.info.label !== m.id &&
          <Typography variant="body2" color="text.secondary">
            {m.info.label}</Typography>}
        {m.info?.is_new &&
          <Chip size="small" label="new" color="success"
                sx={{ ml: "auto" }} />}
        {m.info?.is_beta &&
          <Chip size="small" label="beta" color="warning"
                sx={{ ml: "auto" }} />}
        {m.id === current &&
          <Chip size="small" label="текущая" color="primary"
                sx={{ ml: "auto" }} />}
      </Box>
      {m.description &&
        <Typography variant="body2" color="text.secondary">
          {m.description}</Typography>}
      {(m.info?.cost_summary || m.info?.cost_tier ||
        m.info?.max_context_tokens) && (
        <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 0.5 }}>
          {m.info.cost_summary &&
            <Chip size="small" color="success" variant="outlined"
                  label={m.info.cost_summary} />}
          {m.info.cost_tier && (m.info.cost_tier === "Free"
            ? <Chip size="small" color="success"
                    icon={<MoneyOffIcon sx={{ fontSize: 14 }} />}
                    label="бесплатно" />
            : <Chip size="small" variant="outlined"
                    label={"тариф: " + m.info.cost_tier} />)}
          {m.info.max_context_tokens &&
            <Chip size="small" variant="outlined"
                  label={"контекст: " +
                    Math.round(m.info.max_context_tokens / 1000) + "K"} />}
          {m.info.max_output_tokens &&
            <Chip size="small" variant="outlined"
                  label={"вывод: " +
                    Math.round(m.info.max_output_tokens / 1000) + "K"} />}
        </Box>)}
      {m.info && Object.keys(m.info).length > 0 &&
        <Box component="pre" sx={{
          mt: 0.5, mb: 0, p: 0.8, fontSize: 11, lineHeight: 1.4,
          bgcolor: "#f5f5f5", borderRadius: 1, overflowX: "auto",
          whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {Object.entries(m.info)
            .filter(([k]) => !["model_uid", "id", "name", "description",
                               "display_name", "label", "cost_summary",
                               "cost_tier", "max_context_tokens",
                               "max_output_tokens", "is_new",
                               "is_beta"].includes(k))
            .map(([k, v]) => `${k}: ${
              typeof v === "object" && v !== null
                ? JSON.stringify(v, null, 2)
                : v}`)
            .join("\n") || ""}
        </Box>}
    </CardContent>
  </Card>
);

export default function ModelsPage({ accent, onClose, toast }) {
  const [data, setData] = useState(null);   // null = грузим
  const [current, setCurrent] = useState("");
  const [agent, setAgent] = useState("");   // движок каталога
  const [agents, setAgents] = useState([]); // настроенные из /api/agents
  const [q, setQ] = useState("");           // фильтр по моделям
  const [openFam, setOpenFam] = useState({}); // family -> bool

  useEffect(() => {
    apiJson("/api/agents").then(j => {
      const cfg = (j.agents || []).filter(a => a.configured);
      setAgents(cfg);
      if (!agent && cfg.length) setAgent(j.default || cfg[0].key);
    }).catch(() => setAgent("devin"));
  }, []);

  useEffect(() => {
    if (agent === "") return;
    setData(null); setOpenFam({});
    apiJson("/api/models?fresh=1&agent=" + agent)
      .then(d => { setData(d); setCurrent(d.current || ""); })
      .catch(e => setData({ error: String(e) }));
  }, [agent]);

  const pick = id => post("/api/model", { model: id })
    .then(d => { if (d.ok) { setCurrent(id); toast?.("Модель: " + id); } });

  const ql = q.trim().toLowerCase();
  const models = (data?.models || []).filter(m =>
    !ql || m.id.toLowerCase().includes(ql) ||
    (m.description || "").toLowerCase().includes(ql) ||
    (m.family || "").toLowerCase().includes(ql) ||
    (m.info?.label || "").toLowerCase().includes(ql));

  // группировка по семейству, порядок — как отдал devin
  const groups = [];
  const byFam = new Map();
  for (const m of models) {
    const f = m.family || "Прочее";
    if (!byFam.has(f)) { byFam.set(f, []); groups.push(f); }
    byFam.get(f).push(m);
  }
  const famOpen = f => q.trim() ? true : !!openFam[f];

  return (
    <Box sx={{ width: "100%" }}>
      <AppBar position="sticky" color="primary"
              sx={{ bgcolor: accent, top: 0, zIndex: 5 }}>
        <Toolbar variant="dense">
          <SmartToyIcon sx={{ mr: 1 }} />
          {agents.length > 1 ? (
            <TextField select size="small" value={agent}
                       onChange={e => setAgent(e.target.value)}
                       sx={{ mr: 1, "& .MuiInputBase-input": {
                              color: "#fff", fontSize: 15,
                              fontWeight: 600, py: 0.4 },
                            "& .MuiOutlinedInput-notchedOutline": {
                              borderColor: "rgba(255,255,255,.35)" },
                            "& .MuiSvgIcon-root": { color: "#fff" } }}>
              {agents.map(a => (
                <MenuItem key={a.key} value={a.key}>
                  {"Модели " + a.label}</MenuItem>))}
            </TextField>
          ) : (
            <Typography variant="h6" sx={{ fontSize: 16, mr: 1 }}>
              {"Модели " + (data?.agent_label ||
                agents[0]?.label || "Devin")}
            </Typography>)}
          <Box sx={{ flex: 1 }} />
          {data?.fresh &&
            <Chip size="small" label="живой список"
                  sx={{ bgcolor: "rgba(255,255,255,.2)", color: "#fff",
                        mr: 1 }} />}
          {!!data?.at &&
            <Typography sx={{ fontSize: 11, opacity: .8, mr: 1,
                              whiteSpace: "nowrap" }}>
              опрос {new Date(data.at * 1000)
                .toLocaleString("ru-RU",
                  { day: "2-digit", month: "2-digit",
                    hour: "2-digit", minute: "2-digit" })}
            </Typography>}
          <Tooltip title="закрыть">
            <IconButton color="inherit" onClick={onClose}>
              <CloseIcon />
            </IconButton>
          </Tooltip>
        </Toolbar>
      </AppBar>
      <Box sx={{ p: 1.5, pb: "150px", maxWidth: 900,
                 mx: "auto", width: "100%" }}>
        {data && (
          <TextField size="small" fullWidth value={q}
                     onChange={e => setQ(e.target.value)}
                     placeholder={`поиск — ${data.models.length} моделей, ` +
                                  `${groups.length} семейств`}
                     sx={{ mb: 1, bgcolor: "#fff" }} />)}
        {!data && (
          <Box sx={{ display: "flex", gap: 1, alignItems: "center",
                     justifyContent: "center", pt: 4 }}>
            <CircularProgress size={20} />
            <Typography color="text.secondary">
              {"запрашиваю список у " + agent + "…"}</Typography>
          </Box>)}
        {data?.error &&
          <Typography color="error">{data.error}</Typography>}
        {data && !data.error && !models.length &&
          <Typography color="text.secondary">
            {q ? "по фильтру ничего" : "моделей нет"}</Typography>}

        {groups.map(f => (
          <Box key={f} sx={{ mb: 0.5 }}>
            <ListItemButton
              onClick={() => setOpenFam(o => ({ ...o, [f]: !o[f] }))}
              sx={{ borderRadius: 1, bgcolor: "#eceff1",
                    "&:hover": { bgcolor: "#e0e4e7" } }}>
              <ExpandMoreIcon sx={{
                fontSize: 18, mr: 0.5, transition: "transform .25s",
                transform: famOpen(f) ? "rotate(180deg)" : "none" }} />
              <Typography sx={{ fontWeight: 600, fontSize: 14 }}>
                {f}</Typography>
              {byFam.get(f).some(m => m.info?.cost_tier === "Free") &&
                <Chip size="small" color="success"
                      icon={<MoneyOffIcon sx={{ fontSize: 13 }} />}
                      label="FREE"
                      sx={{ ml: 1, height: 20, fontSize: 11 }} />}
              <Chip size="small" label={byFam.get(f).length}
                    sx={{ ml: "auto", height: 20, fontSize: 11 }} />
            </ListItemButton>
            <Collapse in={famOpen(f)}>
              <Box sx={{ pt: 1 }}>
                {byFam.get(f).map(m => (
                  <ModelCard key={m.id} m={m} current={current}
                             onPick={pick} />))}
              </Box>
            </Collapse>
          </Box>))}
      </Box>
    </Box>
  );
}
