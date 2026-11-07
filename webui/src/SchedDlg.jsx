// «⏱ Расписание» колонки — периодические задачи (cron, 5 полей
// «мин час день мес дн», как в linux). Каждое срабатывание ставит
// НОВУЮ карточку в эту колонку её дефолтами; опция «убирать
// предыдущую» стирает карточку прошлого прогона после завершения
// нового — в колонке виден только последний запуск.
// Открывается из меню ⋯ колонки; расписания создаются, правятся,
// включаются/выключаются и удаляются здесь же.
import { useEffect, useState } from "react";
import {
  Box, Button, Checkbox, Chip, CircularProgress, Dialog,
  DialogActions, DialogContent, DialogTitle, Divider,
  FormControlLabel, IconButton, Skeleton, Stack, TextField,
  Tooltip, Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import { apiJson as get, post } from "./api.js";

const DOW = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
const MONO = { fontFamily: "ui-monospace, Menlo, monospace" };

// человекочитаемая подпись частых форм cron; прочие — показываем
// выражение как есть (и время следующего запуска из ответа API)
function cronDesc(expr) {
  const p = (expr || "").trim().split(/\s+/);
  if (p.length !== 5) return "";
  const [mi, hh, dm, mo, dw] = p;
  const z = n => String(n).padStart(2, "0");
  if (mi === "*" && hh === "*") return "каждую минуту";
  if (/^\*\/\d+$/.test(mi) && hh === "*")
    return "каждые " + mi.slice(2) + " мин";
  if (/^\d+$/.test(mi) && hh === "*")
    return "каждый час в :" + z(mi);
  if (/^\d+$/.test(mi) && /^\d+$/.test(hh)) {
    const t = z(hh) + ":" + z(mi);
    if (dm !== "*" || mo !== "*")
      return "в " + t + " — даты " + dm + ", мес " + mo;
    if (dw !== "*")
      return "в " + t + " — " +
        dw.split(",").map(x => DOW[+x % 7] || x).join(",");
    return "каждый день в " + t;
  }
  return "";
}

const fmtTs = ts => ts
  ? new Date(ts * 1000).toLocaleString("ru-RU",
      { day: "2-digit", month: "2-digit", hour: "2-digit",
        minute: "2-digit" })
  : "—";

export default function SchedDlg({ project, dlg, onClose, toast }) {
  // dlg: {key: "main"|<topic_id>, name}
  const [rows, setRows] = useState(null);
  const [text, setText] = useState("");
  const [cron, setCron] = useState("");
  const [clean, setClean] = useState(false);
  const [editId, setEditId] = useState(null);
  const [delId, setDelId] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    if (!dlg) return;
    try {
      const d = await get("/api/sched?project=" +
        encodeURIComponent(project || "") + "&topic=" +
        encodeURIComponent(dlg.key));
      if (d.ok) setRows(d.schedules || []);
    } catch (e) { /* сеть — оставляем старый список */ }
  };
  useEffect(() => {
    setRows(null); setText(""); setCron(""); setClean(false);
    setEditId(null); setDelId(null);
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [dlg?.key, project]);   // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (busy || !text.trim() || !cron.trim()) return;
    setBusy(true);
    try {
      const body = { action: editId ? "update" : "create",
        project, topic: dlg.key, prompt: text.trim(),
        cron: cron.trim(), autoclean: clean };
      if (editId) body.id = editId;
      const d = await post("/api/sched", body);
      if (d.ok) {
        toast?.(editId ? "Расписание сохранено" : "Расписание создано");
        setText(""); setCron(""); setClean(false); setEditId(null);
        load();
      } else toast?.("Ошибка: " + (d.error || "?"));
    } catch (e) { toast?.("Сеть: " + e); }
    setBusy(false);
  };

  const upd = async (r, patch) => {
    const d = await post("/api/sched",
      { action: "update", project, id: r.id, ...patch });
    if (d.ok) load();
    else toast?.("Ошибка: " + (d.error || "?"));
  };
  const fire = async r => {
    const d = await post("/api/sched",
      { action: "fire", project, id: r.id });
    toast?.(d.ok ? "Задача поставлена в очередь"
                : "Ошибка: " + (d.error || "?"));
    if (d.ok) load();
  };
  const del = async r => {
    const d = await post("/api/sched",
      { action: "delete", project, id: r.id });
    if (d.ok) { setDelId(null); load(); }
    else toast?.("Ошибка: " + (d.error || "?"));
  };
  const startEdit = r => {
    setEditId(r.id); setText(r.prompt); setCron(r.cron);
    setClean(!!r.autoclean); setDelId(null);
  };

  const icoSx = { p: 0.2 };
  return (
    <Dialog open={!!dlg} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle sx={{ fontSize: 15, fontWeight: 600,
                         pt: 2, pb: 0.5, pr: 5 }}>
        ⏱ Расписание — {dlg?.name}
        <Tooltip title="закрыть (Esc)"><span>
          <IconButton onClick={onClose} size="small"
            sx={{ position: "absolute", right: 8, top: 8 }}>
            <CloseIcon sx={{ fontSize: 17 }} />
          </IconButton>
        </span></Tooltip>
      </DialogTitle>
      <DialogContent sx={{ pt: "10px !important" }}>
        <Typography variant="caption" color="text.secondary">
          Каждый запуск создаёт новую карточку в этой колонке с её
          настройками; cron — «мин час день мес дн», локальное время
          воркера.
        </Typography>
        <Stack spacing={1} sx={{ mt: 1.2 }}>
          {rows === null &&
            <Skeleton variant="rounded" height={52} />}
          {rows !== null && !rows.length &&
            <Typography variant="body2" color="text.secondary"
                        sx={{ fontSize: 12.5, py: 0.5 }}>
              Расписаний пока нет — создайте первое ниже.
            </Typography>}
          {(rows || []).map(r => (
            <Box key={r.id} sx={{ border: "1px solid",
                borderColor: "divider", borderRadius: "10px",
                px: 1, py: 0.7, opacity: r.enabled ? 1 : 0.55 }}>
              <Box sx={{ display: "flex", alignItems: "flex-start",
                         gap: 0.4 }}>
                <Typography sx={{ flex: 1, minWidth: 0, fontSize: 12.5,
                  display: "-webkit-box", WebkitLineClamp: 2,
                  WebkitBoxOrient: "vertical", overflow: "hidden",
                  wordBreak: "break-word" }}>
                  {r.prompt}
                </Typography>
                <Tooltip title="запустить сейчас"><span>
                  <IconButton size="small" sx={icoSx}
                    onClick={() => fire(r)}>
                    <PlayArrowIcon sx={{ fontSize: 16 }} />
                  </IconButton></span></Tooltip>
                <Tooltip title="править"><span>
                  <IconButton size="small" sx={icoSx}
                    onClick={() => startEdit(r)}>
                    <EditOutlinedIcon sx={{ fontSize: 15 }} />
                  </IconButton></span></Tooltip>
                <Tooltip title="удалить"><span>
                  <IconButton size="small" sx={icoSx}
                    onClick={() => setDelId(r.id)}>
                    <DeleteOutlineIcon sx={{ fontSize: 15 }} />
                  </IconButton></span></Tooltip>
              </Box>
              <Box sx={{ display: "flex", alignItems: "center",
                         gap: 0.7, flexWrap: "wrap" }}>
                <Typography sx={{ ...MONO, fontSize: 11,
                                  color: "text.secondary" }}>
                  {r.cron}
                </Typography>
                <Chip size="small" variant="outlined"
                  label={cronDesc(r.cron) || "см. выражение"}
                  sx={{ height: 16, fontSize: 9.5, borderRadius: "6px",
                        "& .MuiChip-label": { px: "5px" } }} />
                <Typography sx={{ fontSize: 10.5,
                                  color: "text.secondary" }}>
                  след.: {r.enabled ? fmtTs(r.next_run) : "выкл"}
                </Typography>
              </Box>
              <Box sx={{ display: "flex", alignItems: "center",
                         gap: 1 }}>
                <FormControlLabel sx={{ m: 0, mr: 0.5 }}
                  control={<Checkbox size="small" checked={!!r.enabled}
                    sx={{ p: 0.3 }}
                    onChange={e => upd(r, { enabled: e.target.checked })} />}
                  label={<Typography sx={{ fontSize: 11 }}>вкл</Typography>} />
                <Tooltip title={"после завершения нового запуска " +
                    "карточка прошлого стирается — в колонке " +
                    "остаётся только последняя"}>
                  <FormControlLabel sx={{ m: 0 }}
                    control={<Checkbox size="small"
                      checked={!!r.autoclean} sx={{ p: 0.3 }}
                      onChange={e =>
                        upd(r, { autoclean: e.target.checked })} />}
                    label={<Typography sx={{ fontSize: 11 }}>
                             убирать предыдущую</Typography>} />
                </Tooltip>
                {delId === r.id &&
                  <Box sx={{ display: "flex", alignItems: "center",
                             gap: 0.5, ml: "auto" }}>
                    <Typography sx={{ fontSize: 11,
                                      color: "error.main" }}>
                      удалить?
                    </Typography>
                    <Button size="small" color="error"
                      onClick={() => del(r)}
                      sx={{ textTransform: "none", minWidth: 0,
                            fontSize: 11, p: "0 4px" }}>
                      да</Button>
                    <Button size="small" onClick={() => setDelId(null)}
                      sx={{ textTransform: "none", minWidth: 0,
                            fontSize: 11, p: "0 4px" }}>
                      нет</Button>
                  </Box>}
              </Box>
            </Box>))}
        </Stack>
        <Divider sx={{ my: 1.4 }} />
        <Typography variant="caption" color="text.secondary">
          {editId ? "Правка расписания #" + editId
                  : "Новое расписание"}
        </Typography>
        <Stack spacing={1} sx={{ mt: 0.8 }}>
          <TextField multiline minRows={2} maxRows={6} fullWidth
            size="small" value={text} disabled={busy}
            onChange={e => setText(e.target.value)}
            placeholder="Текст задачи — каждый запуск ставит её новой карточкой"
            sx={{ "& .MuiInputBase-root": { fontSize: 12.5 } }} />
          <Box sx={{ display: "flex", gap: 1, alignItems: "center" }}>
            <TextField size="small" value={cron} disabled={busy}
              onChange={e => setCron(e.target.value)}
              placeholder="*/15 * * * *"
              sx={{ flex: 1, "& input": { ...MONO, fontSize: 12.5 } }} />
            {cronDesc(cron) &&
              <Chip size="small" label={cronDesc(cron)}
                sx={{ height: 20, fontSize: 10.5, borderRadius: "7px",
                      flexShrink: 0 }} />}
          </Box>
          <FormControlLabel sx={{ m: 0 }}
            control={<Checkbox size="small" checked={clean}
              sx={{ p: 0.3 }} disabled={busy}
              onChange={e => setClean(e.target.checked)} />}
            label={<Typography sx={{ fontSize: 12 }}>
                     убирать предыдущую карточку после запуска
                     (в колонке виден только последний прогон)
                   </Typography>} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 2, pb: 1.5 }}>
        {editId &&
          <Button onClick={() => { setEditId(null); setText("");
                                   setCron(""); setClean(false); }}
                  sx={{ textTransform: "none" }}>
            отменить правку</Button>}
        <Box sx={{ flex: 1 }} />
        <Button variant="contained" disableElevation onClick={save}
          disabled={busy || !text.trim() || !cron.trim()}
          startIcon={busy
            ? <CircularProgress size={13} thickness={6} /> : null}
          sx={{ textTransform: "none", borderRadius: "9px" }}>
          {editId ? "Сохранить" : "Создать"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
