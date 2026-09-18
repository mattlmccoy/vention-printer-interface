import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// A per-build identifier so every deploy is distinguishable even between semver bumps (the user
// asked to always see the version move). Git short SHA when available, else the build date.
function buildId(): string {
  try {
    return execSync("git rev-parse --short HEAD", { encoding: "utf8" }).trim();
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

// The single-source version lives in the backend package; bake it into the build so the site can
// tell whether the local operator (which reports its own version at /api/health) is behind it.
function appVersion(): string {
  try {
    const src = readFileSync(fileURLToPath(new URL(
      "../backend/vention_printer_interface/__init__.py", import.meta.url)), "utf8");
    return /__version__\s*=\s*"([^"]+)"/.exec(src)?.[1] ?? "0.0.0";
  } catch {
    return "0.0.0";
  }
}

// Dev server proxies API + WebSocket to the Python operator on :8020.
// VITE_BASE="/vention-printer-interface/" for the GitHub Pages build; default "/" for the operator.
export default defineConfig({
  base: process.env.VITE_BASE ?? "/",
  define: { __APP_VERSION__: JSON.stringify(appVersion()), __BUILD_ID__: JSON.stringify(buildId()) },
  plugins: [react()],
  server: {
    port: 5175,
    proxy: {
      "/api": "http://127.0.0.1:8020",
      "/ws": { target: "ws://127.0.0.1:8020", ws: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
