import { useEffect, useRef } from "react";
import { labelCandidates, type VideoInput } from "../lib/webcam.ts";

// Low-res, low-fps preview so two identical 20MP cameras can stream side-by-side on one USB hub
// without saturating it — the tile only has to be recognisable, not sharp. The real view opens at
// full resolution once the operator has picked.
const PREVIEW: MediaTrackConstraints = {
  width: { ideal: 640 },
  height: { ideal: 480 },
  frameRate: { ideal: 15 },
};

/** One live preview tile for a single camera. Opens its own low-res stream and stops it on unmount
 * (or when the deviceId changes), so leaving the picker frees the camera + hub bandwidth. */
function Tile({
  cam,
  display,
  selected,
  badge,
  onPick,
}: {
  cam: VideoInput;
  display: string;
  selected: boolean;
  badge?: string;
  onPick: (deviceId: string) => void;
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
        const stream = await md.getUserMedia({ video: { deviceId: { exact: cam.deviceId }, ...PREVIEW } });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) videoRef.current.srcObject = stream;
        if (errRef.current) errRef.current.style.display = "none";
      } catch {
        // Camera busy (already open elsewhere) or hub can't supply another stream: show the name
        // only. The operator can still pick it; the full-res open will retry on selection.
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

  return (
    <button
      type="button"
      className="cam-tile"
      onClick={() => onPick(cam.deviceId)}
      aria-pressed={selected}
      title={`use ${display} as the overview`}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        width: 176,
        height: "auto", // override any ancestor button height (e.g. .banner button { height:30px })
        flexShrink: 0, // keep the tile full width in a wrapping flex row, never squished
        padding: 4,
        cursor: "pointer",
        borderRadius: 8,
        border: selected ? "2px solid var(--accent, #f5a742)" : "1px solid var(--line, #2a2f3a)",
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
        {selected && badge && (
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
        {selected ? "✓ " : ""}
        {display}
      </span>
    </button>
  );
}

/** A grid of live camera tiles for identifying which physical camera is which. Duplicate labels
 * (two identical ELPs) are numbered #1/#2 via labelCandidates, and the live feed itself tells them
 * apart — the operator clicks the one showing the print bed. */
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
        <Tile key={c.deviceId} cam={c} display={c.display} selected={c.deviceId === selectedId} badge={badge} onPick={onPick} />
      ))}
    </div>
  );
}
