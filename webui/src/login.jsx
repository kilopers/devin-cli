// Login page — React + MUI card; the form itself is a plain POST /login.
import React from "react";
import { createRoot } from "react-dom/client";
import { createTheme, ThemeProvider } from "@mui/material/styles";
import {
  Alert, Box, Button, Card, CardContent, CardActions, CssBaseline,
  InputAdornment, TextField, Typography,
} from "@mui/material";
import PersonIcon from "@mui/icons-material/Person";
import LockIcon from "@mui/icons-material/Lock";

// та же дизайн-система, что и в основной панели (webui.jsx): Inter,
// акцент #5e6ad2, скругления, кнопки без теней
const theme = createTheme({
  palette: {
    primary: { main: "#5e6ad2" },
    background: { default: "#f6f7fa", paper: "#ffffff" },
    text: { primary: "#1c2128", secondary: "#5d6673" },
    divider: "rgba(28,33,40,.09)",
  },
  typography: {
    fontFamily: '"Inter", "Segoe UI", system-ui, -apple-system, ' +
                '"Helvetica Neue", Arial, sans-serif',
    button: { textTransform: "none" },
  },
  shape: { borderRadius: 10 },
  components: {
    MuiCard: { styleOverrides: { root: ({ theme: t }) => ({
      borderRadius: 16, boxShadow: "none",
      border: `1px solid ${t.palette.divider}` }) } },
    MuiButton: { defaultProps: { disableElevation: true },
      styleOverrides: { root: {
        textTransform: "none", borderRadius: 9, fontWeight: 500 } } },
    MuiOutlinedInput: { styleOverrides: { root: {
      borderRadius: 10 } } },
    MuiAlert: { styleOverrides: { root: { borderRadius: 10 } } },
  },
});
const adorn = icon => (
  <InputAdornment position="start">{icon}</InputAdornment>);

function Login() {
  // куда вернуться после входа — пришёл с ?next=… (например, ссылка
  // на конкретный проект ?project=X)
  const next = new URLSearchParams(location.search).get("next") || "";
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ minHeight: "100vh", display: "flex", alignItems: "center",
                 justifyContent: "center", bgcolor: "#f6f7fa", p: 2 }}>
        <Card component="form" method="post" action="/login"
              sx={{ width: 380, maxWidth: "100%" }}>
          <CardContent
              sx={{ display: "flex", flexDirection: "column", gap: 2, p: 3 }}>
            <Box component="img" src="/static/favicon.svg" alt="Devin"
                 sx={{ height: 48, width: 48, alignSelf: "center" }} />
            <Typography variant="h5" component="h1">
              <Box component="span" sx={{ color: "primary.main" }}>Devin</Box>
              {" Worker"}
            </Typography>
            {window.LOGIN_ERROR &&
              <Alert severity="error">Неверный логин или пароль</Alert>}
            {next && <input type="hidden" name="next" value={next} />}
            <TextField name="user" label="Логин" autoComplete="username"
                       autoFocus required fullWidth
                       slotProps={{ input: {
                         startAdornment: adorn(<PersonIcon />) } }} />
            <TextField name="password" label="Пароль" type="password"
                       autoComplete="current-password" required fullWidth
                       slotProps={{ input: {
                         startAdornment: adorn(<LockIcon />) } }} />
          </CardContent>
          <CardActions sx={{ p: 3, pt: 0 }}>
            <Button type="submit" variant="contained" size="large" fullWidth>
              Войти
            </Button>
          </CardActions>
        </Card>
      </Box>
    </ThemeProvider>
  );
}

if ("serviceWorker" in navigator)
  navigator.serviceWorker.register("/sw.js").catch(() => {});

createRoot(document.getElementById("root")).render(<Login />);
