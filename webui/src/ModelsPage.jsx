// Страница «Модели» — отдельный экран (не модалка): при открытии
// синхронно запрашивает у devin свежий список (GET /api/models?fresh=1)
// и выводит каждую модель карточкой со всей информацией, что devin отдал.
import { useEffect, useState } from "react";
import {
  AppBar, Box, Card, CardContent, Chip, CircularProgress, IconButton,
  Radio, Toolbar, Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import { apiJson, post } from "./api.js";

export default function ModelsPage({ accent, onClose, toast }) {
  const [data, setData] = useState(null);   // null = грузим
  const [current, setCurrent] = useState("");

  useEffect(() => {
    setData(null);
    apiJson("/api/models?fresh=1")
      .then(d => { setData(d); setCurrent(d.current || ""); })
      .catch(e => setData({ error: String(e) }));
  }, []);

  const pick = id => post("/api/model", { model: id })
    .then(d => { if (d.ok) { setCurrent(id); toast?.("Модель: " + id); } });

  const models = data?.models || [];
  return (
    <Box sx={{ display: "flex", flexDirection: "column",
               flex: "1 1 auto", minHeight: 0, width: "100%",
               height: "calc(100dvh - 60px)", overflow: "hidden" }}>
      <AppBar position="static" color="primary" sx={{ bgcolor: accent }}>
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
      <Box sx={{ flex: 1, minHeight: 0, overflowY: "auto", p: 1.5,
                 maxWidth: 900, mx: "auto", width: "100%",
                 WebkitOverflowScrolling: "touch" }}>
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
          <Typography color="text.secondary">моделей нет</Typography>}
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
