import { useEffect, useRef, type ReactNode } from "react";
import { labelCandidates, type VideoInput } from "../lib/webcam.ts";
import { SETUP_PREVIEW_CONSTRAINTS } from "../lib/camera_ready.ts";

// Low-res, low-fps preview so two identical 20MP cameras can stream side-by-side on one USB hub
// without saturating it — the tile only has to be recognisable, not sharp. The real view opens at
// full resolution once the operator has picked.
/** One live preview tile for a single camera. Opens its own low-res stream and stops it on unmount
 * (or when the deviceId changes), so leaving the picker frees the camera + hub bandwidth. Rendered
 * as a <div> (not a <button>) so ancestor button rules — e.g. the wizard banner's
 * `.banner button { height:30px }` — can't crush the preview box. Clickable only when `onClick` is
 * given; otherwise it is a static tile with an interactive `footer` (e.g. a role dropdown). */
export function CameraTile({
  cam,
  display,
  active,
  badge,
  footer,
  onClick,
}: {
  cam: VideoInput;
  display: string;
  active?: boolean;
  badge?: string;
  footer?: ReactNode;
  onClick?: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const errRef = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    const md = typeof navigator !== "undefined" ? navigator.mediaDevices : undefined;
    if (!md?.getUserMedia) return;
    let cancelled = false;
    (async () => {
      try {
        const stream = await md.getUserMedia({ video: { deviceId: { exact: cam.deviceId }, ...SETUP_PREVIEW_CONSTRAINTS } });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) videoRef.current.srcObject = stream;
        if (errRef.current) errRef.current.style.display = "none";
      } catch {
        // Camera busy (already open elsewhere) or hub can't supply another stream: show the name
        // only. The operator can still assign it; the full-res open will retry when it's used.
        if (errRef.current) errRef.current.style.display = "flex";
      }
    })();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      if (videoRef.current) videoRef.current.srcObject = null;
    };
  }, [cam.deviceId]);

  const clickable = !!onClick;
  return (
    <div
      className="cam-tile"
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      aria-pressed={clickable ? !!active : undefined}
      onClick={onClick}
      onKeyDown={clickable ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick?.(); } } : undefined}
      title={clickable ? `use ${display}` : undefined}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        width: 176,
        flexShrink: 0,
        padding: 4,
        cursor: clickable ? "pointer" : "default",
        borderRadius: 8,
        border: active ? "2px solid var(--accent, #f5a742)" : "1px solid var(--line, #2a2f3a)",
        background: "transparent",
        color: "inherit",
        textAlign: "left",
      }}
    >
      <div style={{ position: "relative", width: "100%", aspectRatio: "4 / 3", background: "#000", borderRadius: 4, overflow: "hidden" }}>
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          style={{ display: "block", width: "100%", height: "100%", objectFit: "cover" }}
        />
        {active && badge && (
          <span
            style={{
              position: "absolute",
              top: 4,
              left: 4,
              padding: "1px 6px",
              borderRadius: 4,
              background: "var(--accent, #f5a742)",
              color: "#111",
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
            }}
          >
            {badge}
          </span>
        )}
        <span
          ref={errRef}
          style={{ display: "none", position: "absolute", inset: 0, alignItems: "center", justifyContent: "center" }}
          className="hint"
        >
          preview busy
        </span>
      </div>
      <span style={{ fontSize: 12, lineHeight: 1.2 }}>
        {active && !footer ? "✓ " : ""}
        {display}
      </span>
      {footer}
    </div>
  );
}

/** A grid of live camera tiles for a single-select pick (e.g. the dock overview re-picker). Click a
 * tile to select it. Duplicate labels (two identical ELPs) are numbered #1/#2 via labelCandidates,
 * and the live feed tells them apart. */
export function CameraTiles({
  candidates,
  selectedId,
  badge,
  onPick,
}: {
  candidates: VideoInput[];
  selectedId: string | null;
  /** Label shown as a pill on the selected tile, e.g. "overview" — makes the assignment explicit. */
  badge?: string;
  onPick: (deviceId: string) => void;
}) {
  const labeled = labelCandidates(candidates);
  return (
    <div className="cam-tiles" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {labeled.map((c) => (
        <CameraTile
          key={c.deviceId}
          cam={c}
          display={c.display}
          active={c.deviceId === selectedId}
          badge={badge}
          onClick={() => onPick(c.deviceId)}
        />
      ))}
    </div>
  );
}
