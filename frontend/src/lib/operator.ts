/**
 * Where the operator (local Python service) lives (FLIR/T&C pattern).
 *
 * Served by the operator itself: same origin, base "". Served from the site (GitHub Pages):
 * http://localhost:8020 by default, overridable and persisted in localStorage.
 */

export const UI_VERSION = "0.1.0";
export const UI_API_VERSION = "0.1";
export const DEFAULT_SITE_BASE = "http://localhost:8020";
const KEY = "vpi.operator.v1";

/** "" for same-origin, an http(s) origin without trailing slash, or null when invalid. */
export function normalizeBase(raw: string): string | null {
  const s = raw.trim().replace(/\/+$/, "");
  if (s === "") return "";
  return /^https?:\/\/[^\s/]+$/i.test(s) ? s : null;
}

export function loadOperatorBase(storage: Storage | null, opts: { siteMode: boolean }): string {
  const fallback = opts.siteMode ? DEFAULT_SITE_BASE : "";
  try {
    const raw = storage?.getItem(KEY);
    if (raw === null || raw === undefined) return fallback;
    const n = normalizeBase(raw);
    return n === null ? fallback : n;
  } catch {
    return fallback;
  }
}

export function saveOperatorBase(storage: Storage | null, base: string): void {
  const n = normalizeBase(base);
  if (n === null) return;
  try { storage?.setItem(KEY, n); } catch { /* ignore */ }
}

export function apiUrl(base: string, path: string): string {
  return `${base}${path}`;
}

export function wsUrl(base: string, path: string, loc?: { protocol: string; host: string }): string {
  if (base === "") {
    const l = loc ?? globalThis.location;
    return `${l.protocol === "https:" ? "wss" : "ws"}://${l.host}${path}`;
  }
  return `${base.replace(/^http/i, "ws")}${path}`;
}

export type Handshake = { level: "ok" } | { level: "warn" | "refuse"; message: string };

/** Compares the UI's API version with the operator's: major mismatch refuses, minor warns. */
export function checkHandshake(ui: string, operator: string | undefined): Handshake {
  if (!operator) return { level: "refuse", message: "operator did not report an API version; update the operator" };
  const [um, un] = ui.split(".").map(Number);
  const [om, on] = operator.split(".").map(Number);
  if (um !== om) return { level: "refuse", message: `operator API ${operator} is incompatible with UI ${ui}; update the operator` };
  if (un !== on) return { level: "warn", message: `operator API ${operator} differs from UI ${ui} (minor); some features may be missing` };
  return { level: "ok" };
}
