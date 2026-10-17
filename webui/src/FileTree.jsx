// Project file tree — lazy per-directory loading: only the top level is
// fetched up front, each expand pulls its children via GET /api/files.
import { useCallback, useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import { SimpleTreeView } from "@mui/x-tree-view/SimpleTreeView";
import { TreeItem } from "@mui/x-tree-view/TreeItem";
import FolderIcon from "@mui/icons-material/Folder";
import InsertDriveFileIcon from "@mui/icons-material/InsertDriveFile";
import { apiJson } from "./api.js";

const Label = ({ icon, name }) => (
  <Box sx={{ display: "flex", alignItems: "center", gap: 0.5, minWidth: 0 }}>
    {icon}
    <Typography variant="body2" noWrap sx={{ color: "#3c4043" }}>
      {name}
    </Typography>
  </Box>
);

export default function FileTree({ project, onError }) {
  // path -> entries[] | "loading" | "error" | undefined (not fetched yet)
  const [dirs, setDirs] = useState({});

  const load = useCallback(async p => {
    setDirs(d => ({ ...d, [p]: "loading" }));
    try {
      const d = await apiJson("/api/files?project=" +
        encodeURIComponent(project || "") +
        "&path=" + encodeURIComponent(p));
      if (!d.ok) throw new Error(d.error || "?");
      setDirs(prev => ({ ...prev, [p]: d.entries }));
    } catch (e) {
      setDirs(prev => ({ ...prev, [p]: "error" }));
      onError?.("Файлы: " + (e.message || e));
    }
  }, [project, onError]);

  // fresh project → drop cache (manual refresh = remount via key)
  useEffect(() => { setDirs({}); load(""); }, [project]);

  const onExpand = (_e, itemId, expanded) => {
    if (expanded && dirs[itemId] === undefined) load(itemId);
  };

  const node = (p, name, isDir) => (
    <Label name={name} icon={isDir
      ? <FolderIcon sx={{ fontSize: 17, color: "#5f6368" }} />
      : <InsertDriveFileIcon sx={{ fontSize: 15, color: "#9aa0a6", ml: "2px" }} />} />
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
    <Box sx={{ overflow: "auto", flex: 1, px: 1, py: 0.5, fontSize: 13 }}>
      <SimpleTreeView onItemExpansionToggle={onExpand}
                      sx={{ "& .MuiTreeItem-content": { py: 0.2 } }}>
        {renderLevel("", dirs[""])}
      </SimpleTreeView>
    </Box>
  );
}
