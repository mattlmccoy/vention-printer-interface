import { useState } from "react";
import { ApiError, saveBlob } from "../lib/api.ts";

/** PNG/PDF download buttons for a seaborn export endpoint. `fetchBlob(fmt)` does the request
 *  (an api.plot* call); `filename` is the base name (extension appended). Shows a per-format
 *  spinner and surfaces a 503 ("plots extra not installed") or any error inline, so a missing
 *  optional dependency degrades to a readable message instead of a silent no-op. */
export function PlotExportButtons({ fetchBlob, filename, label = "Export" }: {
  fetchBlob: (fmt: "png" | "pdf") => Promise<Blob>;
  filename: string;
  label?: string;
}) {
  const [busy, setBusy] = useState<"png" | "pdf" | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function grab(fmt: "png" | "pdf") {
    setBusy(fmt);
    setErr(null);
    try {
      const blob = await fetchBlob(fmt);
      saveBlob(blob, `${filename}.${fmt}`);
    } catch (e) {
      const msg = e instanceof ApiError && e.status === 503
        ? "Install the plots extra: uv sync --extra plots"
        : e instanceof Error ? e.message : String(e);
      setErr(msg);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
      <span style={{ fontSize: 12, color: "var(--muted, #999)" }}>{label}:</span>
      {(["png", "pdf"] as const).map((fmt) => (
        <button
          key={fmt}
          type="button"
          onClick={() => void grab(fmt)}
          disabled={busy !== null}
          style={{ fontSize: 12, padding: "2px 8px" }}
          title={`Download seaborn ${fmt.toUpperCase()}`}
        >
          {busy === fmt ? "…" : `⬇ ${fmt.toUpperCase()}`}
        </button>
      ))}
      {err && <span style={{ fontSize: 12, color: "var(--bad, #b00020)" }}>{err}</span>}
    </div>
  );
}
