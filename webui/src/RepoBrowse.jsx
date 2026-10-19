// «Обзор репозиториев» — fullscreen-список репо со всех git-хостов юзера
// (/api/repos/browse): GitHub + GitLab, описание, кнопка «+» клонирует
// через AddProject (с выбором пространства там же).
import { useEffect, useState } from "react";
import {
  Accordion, AccordionDetails, AccordionSummary, AppBar, Box, Chip,
  CircularProgress, Dialog, IconButton, ListItemButton, Toolbar,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import AddIcon from "@mui/icons-material/Add";
import { apiJson } from "./api.js";

export default function RepoBrowse({ open, onClose, onAdd }) {
  const [repos, setRepos] = useState(null);
  useEffect(() => {
    if (!open) return;
    setRepos(null);
    apiJson("/api/repos/browse")
      .then(d => setRepos(d.repos || []))
      .catch(() => setRepos([]));
  }, [open]);

  const hosts = [...new Set((repos || []).map(r => r.host))];
  return (
    <Dialog open={open} onClose={onClose} fullScreen>
      <AppBar position="sticky" color="primary">
        <Toolbar variant="dense">
          <Typography sx={{ flex: 1, fontWeight: 600 }}>
            Обзор репозиториев</Typography>
          <IconButton color="inherit" onClick={onClose}><CloseIcon /></IconButton>
        </Toolbar>
      </AppBar>
      {repos === null ? (
        <Box sx={{ display: "flex", justifyContent: "center", mt: 6 }}>
          <CircularProgress /></Box>
      ) : repos.length === 0 ? (
        <Typography color="text.secondary" sx={{ p: 3 }}>
          Репозитории не найдены — проверь ключи в «Ключи репозиториев».
        </Typography>
      ) : hosts.map(h => {
        const rs = repos.filter(r => r.host === h);
        return (
        <Accordion key={h} defaultExpanded disableGutters
          sx={{ "&:before": { display: "none" }, boxShadow: "none",
               bgcolor: "transparent" }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}
            sx={{ minHeight: 42, px: 2,
                 "& .MuiAccordionSummary-content": { my: 0.5,
                 alignItems: "center", gap: 1 } }}>
            <Typography fontWeight={600} fontSize={14} sx={{ flex: 1 }}>
              {(h === "github.com" ? "GitHub" : "GitLab") + " · " + h}
            </Typography>
            <Chip size="small" label={rs.length} variant="outlined"
              sx={{ height: 20 }} />
          </AccordionSummary>
          <AccordionDetails sx={{ p: 0 }}>
          {rs.map(r => (
            <ListItemButton key={h + r.name} dense
              disabled={r.added}
              onClick={() => !r.added && onAdd(r)}
              sx={{ px: 2, py: 0.6 }}>
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography variant="body2" noWrap sx={{
                  fontFamily: "ui-monospace, Menlo, monospace",
                  fontSize: 13 }}>
                  {r.name}
                </Typography>
                {r.desc &&
                  <Typography variant="caption" color="text.secondary" noWrap>
                    {r.desc}
                  </Typography>}
              </Box>
              {r.added
                ? <Chip size="small" label="добавлен" variant="outlined"
                        sx={{ height: 18, fontSize: 10 }} />
                : <IconButton size="small" color="primary"
                              title="клонировать">
                    <AddIcon fontSize="small" /></IconButton>}
            </ListItemButton>))}
          </AccordionDetails>
        </Accordion>
        );
      })}
    </Dialog>
  );
}
