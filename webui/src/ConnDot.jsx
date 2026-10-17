// ConnDot — floating connection-liveness dot, bottom-right. Driven by an
// EventSource on /api/stream (SSE keepalive): the browser auto-reconnects
// it (server sends `retry: 2000`), so its readyState maps straight onto
// the three states — green online / amber spinner reconnecting / red
// offline. navigator.onLine refines "offline" vs "reconnecting".
import { useEffect, useState } from "react";
import { Box, CircularProgress, Tooltip, Typography } from "@mui/material";

export default function ConnDot() {
  const [state, setState] = useState("connecting");

  useEffect(() => {
    const es = new EventSource("/api/stream");
    es.onopen = () => setState("online");
    es.onerror = () => setState(
      es.readyState === EventSource.CLOSED || !navigator.onLine
        ? "offline" : "connecting");
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

  const label = state === "online" ? "онлайн"
              : state === "connecting" ? "подключение…"
              : "нет подключения к интернету";

  return (
    <Tooltip title={label} placement="left">
      <Box sx={{
        position: "fixed", right: 14, bottom: 14, zIndex: 1200,
        display: "flex", alignItems: "center", gap: 0.7,
        bgcolor: "rgba(255,255,255,.95)", borderRadius: "12px",
        px: 1, py: 0.6, boxShadow: 2,
      }}>
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
        {state === "offline" && (
          <Typography variant="caption" color="error"
                      sx={{ fontSize: 10.5, fontWeight: 500 }}>
            нет подключения
          </Typography>
        )}
      </Box>
    </Tooltip>
  );
}
