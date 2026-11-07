// «🔔 Расписание» на карточке задачи: карточка становится
// периодической — по cron (5 полей «мин час день мес дн») ставится
// НОВАЯ карточка в той же колонке, где лежит якорь, с его актуальным
// текстом и дефолтами колонки. «Убирать предыдущую» стирает прошлую
// карточку серии после завершения новой — в колонке виден только
// последний запуск. Колокольчик на карточке подсвечен, пока
// расписание включено. Чат-колонок («💬 Диалог») на карточке нет.
import { useEffect, useState } from "react";
import {
  Box, Button, Checkbox, Chip, CircularProgress, Dialog,
  DialogActions, DialogContent, DialogTitle, FormControlLabel,
  IconButton, Stack, TextField, Tooltip, Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import { apiJson as get, post } from "./api.js";

const DOW = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
const MONO = { fontFamily: "ui-monospace, Menlo, monospace" };
// человекопонятные пресеты — просто подставляют cron-выражение
const PRESETS = [
  ["5 мин", "*/5 * * * *"], ["30 мин", "*/30 * * * *"],
  ["час", "0 * * * *"], ["3 ч", "0 */3 * * *"],
  ["12 ч", "0 */12 * * *"], ["сутки", "0 9 * * *"],
  ["неделю", "0 9 * * 1"], ["месяц", "0 9 1 * *"],
];

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

export default function SchedDlg({ project, t, open, onClose, toast,
                                   onChanged }) {
  const [row, setRow] = useState(undefined); // undefined = грузим
  const [cron, setCron] = useState("");
  const [clean, setClean] = useState(false);
  const [en, setEn] = useState(true);
  const [delC, setDelC] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open || !t) return;
    setRow(undefined); setDelC(false); setCron("");
    setClean(false); setEn(true);
    get("/api/sched?project=" + encodeURIComponent(project || "") +
        "&stem=" + encodeURIComponent(t.stem))
      .then(d => {
        const r = (d.schedules || [])[0] || null;
        setRow(r);
        if (r) { setCron(r.cron); setClean(!!r.autoclean);
                 setEn(!!r.enabled); }
      }).catch(() => setRow(null));
  }, [open, t?.stem]);   // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (busy || !cron.trim()) return;
    setBusy(true);
    try {
      const body = { action: row ? "update" : "create", project,
                     cron: cron.trim(), autoclean: clean,
                     enabled: en };
      if (row) body.id = row.id; else body.stem = t.stem;
      const d = await post("/api/sched", body);
      if (d.ok) { toast?.(row ? "Расписание сохранено"
                              : "Задача стала периодической");
                  onChanged?.(); onClose(); }
      else toast?.("Ошибка: " + (d.error || "?"));
    } catch (e) { toast?.("Сеть: " + e); }
    setBusy(false);
  };
  const del = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const d = await post("/api/sched",
                           { action: "delete", project, id: row.id });
      if (d.ok) { toast?.("Расписание удалено");
                  onChanged?.(); onClose(); }
      else toast?.("Ошибка: " + (d.error || "?"));
    } catch (e) { toast?.("Сеть: " + e); }
    setBusy(false);
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle sx={{ fontSize: 15, fontWeight: 600,
                         pt: 2, pb: 0.5, pr: 5 }}>
        🔔 Расписание задачи
        <Tooltip title="закрыть (Esc)"><span>
          <IconButton onClick={onClose} size="small"
            sx={{ position: "absolute", right: 8, top: 8 }}>
            <CloseIcon sx={{ fontSize: 17 }} />
          </IconButton>
        </span></Tooltip>
      </DialogTitle>
      <DialogContent sx={{ pt: "10px !important" }}>
        <Typography variant="caption" color="text.secondary">
          По расписанию в этой же колонке ставится новая карточка
          с текстом этой задачи — колокольчик всегда горит на
          последней. cron — «мин час день мес дн», время воркера.
        </Typography>
        <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5,
                   mt: 1.2 }}>
          {PRESETS.map(([l, c]) => (
            <Chip key={c} size="small" label={l}
              variant={cron === c ? "filled" : "outlined"}
              color={cron === c ? "primary" : "default"}
              onClick={() => setCron(c)}
              sx={{ height: 20, fontSize: 10.5, borderRadius: "7px",
                    cursor: "pointer" }} />))}
        </Box>
        <Stack direction="row" spacing={1} alignItems="center"
               sx={{ mt: 1 }}>
          <TextField size="small" fullWidth value={cron}
            disabled={busy} onChange={e => setCron(e.target.value)}
            placeholder="*/15 * * * *"
            sx={{ "& input": { ...MONO, fontSize: 12.5 } }} />
          {cronDesc(cron) &&
            <Chip size="small" label={cronDesc(cron)}
              sx={{ height: 20, fontSize: 10.5, borderRadius: "7px",
                    flexShrink: 0 }} />}
        </Stack>
        {row?.enabled && row?.next_run &&
          <Typography variant="caption" color="text.secondary"
                      sx={{ display: "block", mt: 0.5 }}>
            следующий запуск: {fmtTs(row.next_run)}
          </Typography>}
        <Stack sx={{ mt: 0.5 }}>
          {row &&
            <FormControlLabel sx={{ m: 0 }}
              control={<Checkbox size="small" checked={en}
                sx={{ p: 0.4 }} disabled={busy}
                onChange={e => setEn(e.target.checked)} />}
              label={<Typography sx={{ fontSize: 12.5 }}>
                       расписание включено</Typography>} />}
          <FormControlLabel sx={{ m: 0 }}
            control={<Checkbox size="small" checked={clean}
              sx={{ p: 0.4 }} disabled={busy}
              onChange={e => setClean(e.target.checked)} />}
            label={<Typography sx={{ fontSize: 12.5 }}>
                     убирать предыдущую карточку (в колонке только
                     последний запуск)</Typography>} />
        </Stack>
        {delC &&
          <Box sx={{ display: "flex", alignItems: "center", gap: 0.7,
                     mt: 0.7 }}>
            <Typography sx={{ fontSize: 12, color: "error.main" }}>
              Удалить расписание? Карточки останутся.
            </Typography>
            <Button size="small" color="error" onClick={del}
              sx={{ textTransform: "none", minWidth: 0, p: "0 4px" }}>
              да</Button>
            <Button size="small" onClick={() => setDelC(false)}
              sx={{ textTransform: "none", minWidth: 0, p: "0 4px" }}>
              нет</Button>
          </Box>}
      </DialogContent>
      <DialogActions sx={{ px: 2, pb: 1.5 }}>
        {row && !delC &&
          <Button color="error" onClick={() => setDelC(true)}
            sx={{ textTransform: "none" }}>Удалить</Button>}
        <Box sx={{ flex: 1 }} />
        <Button onClick={onClose} sx={{ textTransform: "none" }}>
          Отмена</Button>
        <Button variant="contained" disableElevation onClick={save}
          disabled={busy || !cron.trim() || row === undefined}
          startIcon={busy
            ? <CircularProgress size={13} thickness={6} /> : null}
          sx={{ textTransform: "none", borderRadius: "9px" }}>
          {row ? "Сохранить" : "Включить"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
