// ConnDot — floating connection-liveness dot, bottom-right. Driven by an
// EventSource on /api/stream (SSE keepalive): the browser auto-reconnects
// it (server sends `retry: 2000`), so its readyState maps straight onto
// the three states — green online / amber spinner reconnecting / red
// offline. navigator.onLine refines "offline" vs "reconnecting".
// The stream also carries `version` events — when the server's build no
// longer matches the version this page was loaded with, we reload so the
// UI picks up the fresh bundle (SW is network-first for /static/app/).
import { useEffect, useRef, useState } from "react";
import { Box, CircularProgress, Tooltip, Typography } from "@mui/material";

// Single SSE connection shared by the floating dot and the mobile
// bottom bar: { state: "online"|"connecting"|"offline", liveVer }.
export function useConnStatus(version) {
  const [state, setState] = useState("connecting");
  const [liveVer, setLiveVer] = useState(null);
  const baseVer = useRef(null);

  // baseline = the version the page was loaded against (from /api/status)
  useEffect(() => {
    if (version && baseVer.current === null) baseVer.current = version;
  }, [version]);

  useEffect(() => {
    const es = new EventSource("/api/stream");
    es.onopen = () => setState("online");
    es.onerror = () => setState(
      es.readyState === EventSource.CLOSED || !navigator.onLine
        ? "offline" : "connecting");
    es.addEventListener("version", e => {
      try {
        const v = JSON.parse(e.data).v;
        setLiveVer(v);
        // server got a newer build → refresh the whole page
        if (baseVer.current && v !== baseVer.current) location.reload();
      } catch (err) {}
    });
    const off = () => setState("offline");
    const on = () => setState(s => s === "online" ? s : "connecting");
    window.addEventListener("offline", off);
    window.addEventListener("online", on);
    return () => {
      es.close();
      window.removeEventListener("offline", off);
      window.removeEventListener("online", on);
    };
  }, []);

  return { state, liveVer };
}

// Inline status icon — dot / spinner + version (used inside the mobile
// bottom bar and the floating desktop chip).
export function ConnBadge({ conn, showVer = true }) {
  const { state, liveVer } = conn;
  const label = state === "online"
    ? `онлайн · v${liveVer || "?"}`
    : state === "connecting" ? "подключение…"
    : "нет подключения к интернету";
  return (
    <Tooltip title={label} placement="top">
      <Box sx={{ display: "flex", alignItems: "center", gap: 0.6 }}>
        {state === "connecting" ? (
          <CircularProgress size={11} thickness={6}
                            sx={{ color: "#e6a23c" }} />
        ) : (
          <Box sx={{
            width: 10, height: 10, borderRadius: "50%",
            bgcolor: state === "online" ? "#4caf50" : "#f44336",
            boxShadow: state === "online"
              ? "0 0 6px rgba(76,175,80,.8)"
              : "0 0 6px rgba(244,67,54,.8)",
          }} />
        )}
        {showVer && liveVer && (
          <Typography variant="caption" sx={{
            fontSize: 10.5, color: "text.secondary",
            fontFamily: "ui-monospace, Menlo, monospace" }}>
            v{liveVer}
          </Typography>
        )}
        {state === "offline" && (
          <Typography variant="caption" color="error"
                      sx={{ fontSize: 10.5, fontWeight: 500,
                            whiteSpace: "nowrap" }}>
            нет подключения
          </Typography>
        )}
      </Box>
    </Tooltip>
  );
}

// Desktop-only floating chip (the mobile bottom bar embeds ConnBadge).
export default function ConnDot({ conn }) {
  return (
    <Box sx={{
      display: { xs: "none", md: "flex" },
      position: "fixed", right: 14, bottom: 14, zIndex: 1200,
      alignItems: "center", bgcolor: "rgba(255,255,255,.95)",
      borderRadius: "12px", px: 1, py: 0.6, boxShadow: 2,
    }}>
      <ConnBadge conn={conn} />
    </Box>
  );
}
