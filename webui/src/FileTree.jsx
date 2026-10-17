// Project file tree — lazy per-directory loading: only the top level is
// fetched up front, each expand pulls its children via GET /api/files.
// Expanded dirs and scroll position persist per project in localStorage —
// a page reload (or re-login) restores the same view.
import { useCallback, useEffect, useRef, useState } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import { SimpleTreeView } from "@mui/x-tree-view/SimpleTreeView";
import { TreeItem } from "@mui/x-tree-view/TreeItem";
import FolderIcon from "@mui/icons-material/Folder";
import InsertDriveFileIcon from "@mui/icons-material/InsertDriveFile";
import { apiJson } from "./api.js";

const LS_EXP = p => `ft:expanded:${p || "_"}`;
const LS_SCR = p => `ft:scroll:${p || "_"}`;
const lsGet = (k, d) => {
  try { const v = localStorage.getItem(k); return v === null ? d : v; }
  catch (e) { return d; }
};
const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };

const Label = ({ icon, name }) => (
  <Box sx={{ display: "flex", alignItems: "center", gap: 0.5, minWidth: 0 }}>
    {icon}
    <Typography variant="body2" noWrap sx={{ color: "#3c4043" }}>
      {name}
    </Typography>
  </Box>
);

export default function FileTree({ project, onError, onOpenFile }) {
  // path -> entries[] | "loading" | "error" | undefined (not fetched yet)
  const [dirs, setDirs] = useState({});
  const [expanded, setExpanded] = useState([]);
  const boxRef = useRef(null);
  const scrollSave = useRef(null);
  const projRef = useRef(project);
  const scrRestoredFor = useRef(null);   // project whose scroll was applied

  const load = useCallback(async p => {
    setDirs(d => ({ ...d, [p]: "loading" }));
    try {
      const d = await apiJson("/api/files?project=" +
        encodeURIComponent(projRef.current || "") +
        "&path=" + encodeURIComponent(p));
      if (!d.ok) throw new Error(d.error || "?");
      setDirs(prev => ({ ...prev, [p]: d.entries }));
    } catch (e) {
      setDirs(prev => ({ ...prev, [p]: "error" }));
      onError?.("Файлы: " + (e.message || e));
    }
  }, [onError]);

  // fresh project → drop caches, restore saved expansion + scroll
  useEffect(() => {
    projRef.current = project;
    setDirs({}); load("");
    let saved = [];
    try { saved = JSON.parse(lsGet(LS_EXP(project), "[]")) || []; }
    catch (e) { saved = []; }
    setExpanded(saved);
    // lazy-load every saved dir so deep expansions render again
    saved.forEach(p => { if (p) load(p); });
  }, [project]);

  // restore scrollTop once the top level has rendered — twice: right
  // away, then after saved deep dirs finish loading (content grows)
  useEffect(() => {
    const el = boxRef.current;
    if (!el || !Array.isArray(dirs[""]) ||
        scrRestoredFor.current === project) return;
    scrRestoredFor.current = project;
    const apply = () => {
      el.scrollTop = parseInt(lsGet(LS_SCR(project), "0"), 10) || 0;
    };
    apply();
    const t = setTimeout(apply, 800);
    return () => clearTimeout(t);
  }, [dirs, project]);

  const onExpandedChange = (_e, ids) => {
    setExpanded(ids);
    lsSet(LS_EXP(project), JSON.stringify(ids));
  };

  const onExpand = (_e, itemId, isExpanded) => {
    if (isExpanded && dirs[itemId] === undefined) load(itemId);
  };

  const onScroll = e => {
    const top = e.currentTarget.scrollTop;
    clearTimeout(scrollSave.current);
    scrollSave.current = setTimeout(
      () => lsSet(LS_SCR(project), String(top)), 300);
  };

  const node = (p, name, isDir) => isDir ? (
    <Label name={name}
           icon={<FolderIcon sx={{ fontSize: 17, color: "#5f6368" }} />} />
  ) : (
    <Box onClick={ev => { ev.stopPropagation(); onOpenFile?.(p); }}
         title="открыть в редакторе"
         sx={{ display: "flex", alignItems: "center", gap: 0.5, minWidth: 0,
               cursor: "pointer",
               "&:hover": { textDecoration: "underline" } }}>
      <InsertDriveFileIcon sx={{ fontSize: 15, color: "#9aa0a6",
                                 ml: "2px" }} />
      <Typography variant="body2" noWrap sx={{ color: "#3c4043" }}>
        {name}
      </Typography>
    </Box>
  );

  const renderLevel = (path, entries) => {
    if (entries === undefined || entries === "loading")
      return <TreeItem itemId={path + "/~loading"} label="загрузка…" />;
    if (entries === "error")
      return <TreeItem itemId={path + "/~error"} label="ошибка загрузки" />;
    if (!entries.length)
      return <TreeItem itemId={path + "/~empty"} label="пусто" />;
    return entries.map(e => {
      const p = path ? path + "/" + e.name : e.name;
      return e.type === "dir"
        ? <TreeItem key={p} itemId={p} label={node(p, e.name, true)}>
            {renderLevel(p, dirs[p])}
          </TreeItem>
        : <TreeItem key={p} itemId={p} label={node(p, e.name, false)} />;
    });
  };

  return (
    <Box ref={boxRef} onScroll={onScroll}
         sx={{ overflow: "auto", flex: "1 1 auto", minHeight: 0,
               px: 1, py: 0.5, fontSize: 13 }}>
      <SimpleTreeView expandedItems={expanded}
                      onExpandedItemsChange={onExpandedChange}
                      onItemExpansionToggle={onExpand}
                      sx={{ "& .MuiTreeItem-content": { py: 0.2 } }}>
        {renderLevel("", dirs[""])}
      </SimpleTreeView>
    </Box>
  );
}
