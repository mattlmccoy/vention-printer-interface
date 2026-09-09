import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.tsx";
import { SITE_MODE } from "./lib/api.ts";
import "./theme.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// Site build only: the operator-served copy is already local.
if (SITE_MODE && "serviceWorker" in navigator) {
  navigator.serviceWorker.register(`${import.meta.env.BASE_URL}sw.js`).catch(() => undefined);
}
