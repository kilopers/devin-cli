// Страница «Модели» — отдельный экран (не модалка): при открытии
// синхронно запрашивает у devin свежий список (GET /api/models?fresh=1)
// и выводит каждую модель карточкой со всей информацией, что devin отдал.
import { useEffect, useState } from "react";
import {
  AppBar, Box, Card, CardContent, Chip, CircularProgress, IconButton,
  Radio, TextField, Toolbar, Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import { apiJson, post } from "./api.js";

export default function ModelsPage({ accent, onClose, toast }) {
  const [data, setData] = useState(null);   // null = грузим
  const [current, setCurrent] = useState("");
  const [q, setQ] = useState("");           // фильтр по моделям

  useEffect(() => {
    setData(null);
    apiJson("/api/models?fresh=1")
      .then(d => { setData(d); setCurrent(d.current || ""); })
      .catch(e => setData({ error: String(e) }));
  }, []);

  const pick = id => post("/api/model", { model: id })
    .then(d => { if (d.ok) { setCurrent(id); toast?.("Модель: " + id); } });

  const ql = q.trim().toLowerCase();
  const models = (data?.models || []).filter(m =>
    !ql || m.id.toLowerCase().includes(ql) ||
    (m.description || "").toLowerCase().includes(ql) ||
    (m.info?.label || "").toLowerCase().includes(ql));
  return (
    <Box sx={{ width: "100%" }}>
      <AppBar position="sticky" color="primary"
              sx={{ bgcolor: accent, top: 0, zIndex: 5 }}>
        <Toolbar variant="dense">
          <SmartToyIcon sx={{ mr: 1 }} />
          <Typography variant="h6" sx={{ flex: 1, fontSize: 16 }}>
            Модели Devin
          </Typography>
          {data?.fresh &&
            <Chip size="small" label="живой список"
                  sx={{ bgcolor: "rgba(255,255,255,.2)", color: "#fff",
                        mr: 1 }} />}
          <IconButton color="inherit" onClick={onClose}>
            <CloseIcon />
          </IconButton>
        </Toolbar>
      </AppBar>
      <Box sx={{ p: 1.5, pb: "150px", maxWidth: 900,
                 mx: "auto", width: "100%" }}>
        {data && (
          <TextField size="small" fullWidth value={q}
                     onChange={e => setQ(e.target.value)}
                     placeholder={`поиск — ${data.models.length} моделей`}
                     sx={{ mb: 1, bgcolor: "#fff" }} />)}
        {!data && (
          <Box sx={{ display: "flex", gap: 1, alignItems: "center",
                     justifyContent: "center", pt: 4 }}>
            <CircularProgress size={20} />
            <Typography color="text.secondary">
              запрашиваю список у devin…</Typography>
          </Box>)}
        {data?.error &&
          <Typography color="error">{data.error}</Typography>}
        {data && !data.error && !models.length &&
          <Typography color="text.secondary">
            {q ? "по фильтру ничего" : "моделей нет"}</Typography>}
        {models.map(m => (
          <Card key={m.id} variant="outlined"
                onClick={() => pick(m.id)}
                sx={{ mb: 1, cursor: "pointer" }}>
            <CardContent sx={{ py: 1, "&:last-child": { pb: 1 } }}>
              <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                <Radio size="small" checked={m.id === current}
                       sx={{ p: 0.5 }} />
                <Typography sx={{ fontFamily: "monospace", fontWeight: 600,
                                  fontSize: 14 }}>{m.id}</Typography>
                {m.id === current &&
                  <Chip size="small" label="текущая" color="primary"
                        sx={{ ml: "auto" }} />}
              </Box>
              {m.description &&
                <Typography variant="body2" color="text.secondary">
                  {m.description}</Typography>}
              {(m.info?.cost_summary || m.info?.cost_tier ||
                m.info?.max_context_tokens) && (
                <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5,
                           mt: 0.5 }}>
                  {m.info.cost_summary &&
                    <Chip size="small" color="success" variant="outlined"
                          label={m.info.cost_summary} />}
                  {m.info.cost_tier &&
                    <Chip size="small" variant="outlined"
                          label={"тариф: " + m.info.cost_tier} />}
                  {m.info.max_context_tokens &&
                    <Chip size="small" variant="outlined"
                          label={"контекст: " +
                            Math.round(m.info.max_context_tokens / 1000) +
                            "K"} />}
                  {m.info.max_output_tokens &&
                    <Chip size="small" variant="outlined"
                          label={"вывод: " +
                            Math.round(m.info.max_output_tokens / 1000) +
                            "K"} />}
                </Box>)}
              {m.info && Object.keys(m.info).length > 0 &&
                <Box component="pre" sx={{
                  mt: 0.5, mb: 0, p: 0.8, fontSize: 11, lineHeight: 1.4,
                  bgcolor: "#f5f5f5", borderRadius: 1, overflowX: "auto",
                  whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                  {Object.entries(m.info)
                    .filter(([k]) => !["id", "name", "description",
                                       "display_name"].includes(k))
                    .map(([k, v]) => `${k}: ${
                      typeof v === "object" && v !== null
                        ? JSON.stringify(v, null, 2)
                        : v}`)
                    .join("\n") || "доп. полей нет"}
                </Box>}
            </CardContent>
          </Card>))}
      </Box>
    </Box>
  );
}
