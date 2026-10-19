// «Инструкции» — первая секция панели: системная (read-only),
// пользовательская, проектная, custom — подключаются галочкой.
// Тело показывается отрендеренным Markdown-читалкой; меняются
// инструкции только агентом (задачей). Удалить можно только свою
// custom-инструкцию — с подтверждением.
import { useEffect, useRef, useState } from "react";
import {
  Box, Checkbox, Chip, Collapse, Dialog, DialogActions,
  DialogContent, DialogTitle, ListItemButton, Typography, Button,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import MenuBookIcon from "@mui/icons-material/MenuBook";
import DeleteIcon from "@mui/icons-material/Delete";
import IconButton from "@mui/material/IconButton";
import { apiJson, post } from "./api.js";
import Markdown from "./Markdown.jsx";

export default function Instr({ project, open, onToggle, toast }) {
  const [rows, setRows] = useState([]);
  const [view, setView] = useState(null);      // открытая в модалке
  const projRef = useRef(project);
  projRef.current = project;

  const load = async () => {
    try {
      const d = await apiJson("/api/instr?project=" +
        encodeURIComponent(projRef.current || ""));
      if (d.ok) setRows(d.instructions || []);
    } catch (e) {}
  };
  useEffect(() => { setRows([]); load(); }, [project]);

  const del = async () => {
    if (!window.confirm(`Удалить инструкцию «${view.name}»?`)) return;
    const d = await post("/api/instr", {
      action: "delete", id: view.id, project: projRef.current });
    toast?.(d.ok ? "Инструкция удалена"
                : "Ошибка: " + (d.error || "?"));
    if (d.ok) { setView(null); load(); }
  };

  const attach = async (r, on) => {
    const d = await post("/api/instr", {
      action: on ? "attach" : "detach", id: r.id,
      project: projRef.current });
    if (d.ok) load();
    else toast?.("Ошибка: " + (d.error || "?"));
  };

  const system = rows.find(r => r.kind === "system");
  const common = rows.find(r => r.kind === "user");
  const projInstr = rows.find(r => r.kind === "project");
  const customs = rows.filter(r => r.kind === "custom");
  const count = rows.filter(
    r => r.kind !== "custom" || r.attached).length;

  return (<>
    <ListItemButton dense onClick={onToggle} sx={{ px: 1.5, py: 0.5 }}>
      {open ? <ExpandLessIcon sx={{ fontSize: 18 }} />
            : <ExpandMoreIcon sx={{ fontSize: 18 }} />}
      <MenuBookIcon sx={{ fontSize: 16, ml: 0.5 }} />
      <Typography variant="body2" sx={{ fontWeight: 500, ml: 0.5 }}>
        Инструкции
      </Typography>
      <Chip size="small" label={count}
            sx={{ ml: 1, height: 18, fontSize: 11 }} />
    </ListItemButton>
    <Collapse in={open}>
      <Box>
        {system && (
          <ListItemButton dense onClick={() => setView(system)}
                          sx={{ px: 1.5, py: 0.3 }}>
            <Checkbox size="small" checked disabled
                      sx={{ p: 0.3, mr: 0.5 }} />
            <Typography variant="body2" noWrap sx={{
              flex: 1, fontSize: 12.5, fontStyle: "italic",
              color: "text.secondary" }}>
              {system.name}
            </Typography>
            <Chip size="small" label="системная" color="primary"
                  variant="outlined" sx={{ height: 16, fontSize: 10 }} />
          </ListItemButton>)}
        {common && (
          <ListItemButton dense onClick={() => setView(common)}
                          sx={{ px: 1.5, py: 0.3 }}>
            <Checkbox size="small" checked disabled
                      sx={{ p: 0.3, mr: 0.5 }}
                      title="подключается ко всем проектам" />
            <Typography variant="body2" noWrap
                        sx={{ flex: 1, fontSize: 12.5 }}>
              {common.name}
            </Typography>
            <Chip size="small" label="моя" variant="outlined"
                  sx={{ height: 16, fontSize: 10 }} />
          </ListItemButton>)}
        {projInstr && (
          <ListItemButton dense onClick={() => setView(projInstr)}
                          sx={{ px: 1.5, py: 0.3 }}>
            <Checkbox size="small" checked disabled
                      sx={{ p: 0.3, mr: 0.5 }}
                      title="проектная — отцепить нельзя" />
            <Typography variant="body2" noWrap
                        sx={{ flex: 1, fontSize: 12.5 }}>
              {projInstr.name}
            </Typography>
            <Chip size="small" label="проектная" variant="outlined"
                  color="secondary" sx={{ height: 16, fontSize: 10 }} />
          </ListItemButton>)}
        {customs.map(r => (
          <ListItemButton key={r.id} dense onClick={() => setView(r)}
                          sx={{ px: 1.5, py: 0.3 }}>
            <Checkbox size="small" checked={!!r.attached}
                      disabled={!r.mine}
                      sx={{ p: 0.3, mr: 0.5 }}
                      title={r.mine
                        ? "подключена к проекту"
                        : "инструкция владельца — нельзя править"}
                      onClick={e => e.stopPropagation()}
                      onChange={e => attach(r, e.target.checked)} />
            <Typography variant="body2" noWrap
                        sx={{ flex: 1, fontSize: 12.5 }}>
              {r.name}
            </Typography>
          </ListItemButton>))}
      </Box>
    </Collapse>

    <Dialog open={!!view} onClose={() => setView(null)}
            fullWidth maxWidth="sm"
            PaperProps={{ sx: {
              // на мобильной — почти во всю ширину экрана
              m: { xs: "4px", md: "32px" },
              width: { xs: "calc(100vw - 8px)", md: "auto" },
              maxWidth: { xs: "calc(100vw - 8px)", md: "sm" } } }}>
      <DialogTitle sx={{ fontSize: 16,
                         p: { xs: "12px 12px 4px", md: "16px 24px" } }}>
        {view?.kind === "system" ? "Системная инструкция"
          : view?.kind === "user" ? "Пользовательская инструкция"
          : view?.kind === "project" ? "Проектная инструкция"
          : view?.name}
      </DialogTitle>
      <DialogContent sx={{ p: { xs: "8px 12px", md: "20px 24px" } }}>
        {view?.body
          ? <Markdown text={view.body} />
          : <Typography variant="body2" color="text.secondary">
              пусто — агент заполнит её задачей «допиши инструкцию»,
              или открой голосом
            </Typography>}
      </DialogContent>
      <DialogActions sx={{ flexDirection: "column", alignItems: "stretch",
                           gap: 0.5, px: { xs: 1.5, md: 3 },
                           pb: { xs: 1, md: 2 } }}>
        <Box sx={{ display: "flex", alignItems: "center" }}>
          {view?.kind === "custom" && view?.mine &&
            <IconButton onClick={del} title="удалить" sx={{ mr: "auto" }}>
              <DeleteIcon fontSize="small" />
            </IconButton>}
          <Box sx={{ ml: "auto" }}>
            <Button onClick={() => setView(null)}>Закрыть</Button>
          </Box>
        </Box>
        <Typography variant="caption" color="text.secondary"
                    sx={{ fontSize: 10.5, textAlign: "center" }}>
          инструкции изменяются только агентом (задачей)
        </Typography>
      </DialogActions>
    </Dialog>
  </>);
}
