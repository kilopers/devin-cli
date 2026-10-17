// Bundles the React+MUI web UI into ../static/app/*.js (ESM, minified,
// code-split — CodeMirror language packs lazy-load as chunks/).
// Templates must load entries with <script type="module">.
// Run: cd webui && npm ci && npm run build
// In the Docker image this runs in a dedicated node build stage —
// see Dockerfile (the repo itself ships only sources).
import { build } from "esbuild";
import path from "node:path";
import { fileURLToPath } from "node:url";

const outdir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)), "../static/app");

await build({
  entryPoints: ["src/webui.jsx", "src/login.jsx"],
  bundle: true,
  minify: true,
  format: "esm",
  splitting: true,
  chunkNames: "chunks/[name]-[hash]",
  jsx: "automatic",
  define: { "process.env.NODE_ENV": '"production"' },
  outdir,
  logLevel: "info",
});
