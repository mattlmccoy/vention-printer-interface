import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API + WebSocket to the Python operator on :8020.
// VITE_BASE="/vention-printer-interface/" for the GitHub Pages build; default "/" for the operator.
export default defineConfig({
  base: process.env.VITE_BASE ?? "/",
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
