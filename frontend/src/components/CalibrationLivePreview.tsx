import { useEffect, useRef, useState } from "react";
import { api, type AutocalPreview } from "../lib/api.ts";
import type { BoardDef } from "../lib/board_def.ts";
import { loadRoleMap } from "../lib/camera_roles.ts";
import { loadCameraSettings } from "../lib/overview_settings.ts";
import { convexHull, scaleOverlay, type Pt } from "../lib/overlay_geom.ts";
import { CalibrationOverlay } from "./CalibrationOverlay.tsx";
import { useLiveCamera } from "./useLiveCamera.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;
const MAX_W = 1280;
const PERIOD_MS = 500;

/** Live science-camera view on the Calibrate page with the board's identified points drawn ON it
 *  (plan Task 7): green = chessboard corners (with id), amber = marker corners + outlines, and the
 *  area already covered by sweep photos (green dashed) when the live frame has the photos' shape.
 *  Look-only: a small frame goes to POST /api/vision/autocal/preview every 0.5 s; no motion. It
 *  pauses for full-resolution stills (camera bus) like every live view. */
export function CalibrationLivePreview({ board, covered }: {
  board: BoardDef;
  /** Points already seen in sweep photos, in photo pixels, with that photo size. */
  covered?: { size: [number, number]; points: Pt[] } | null;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [reopen, setReopen] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<AutocalPreview | null>(null);
  const stop = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  };
  const live = useLiveCamera(stop, () => setReopen((n) => n + 1));
  const deviceId = loadRoleMap(storage).science;

  useEffect(() => {
    if (!deviceId || live.paused) return;
    let cancelled = false;
    // Ask for the still's aspect ratio so the live frame and the sweep photos show the same view.
    const [sw, sh] = loadCameraSettings(storage, "science").resolution.split("x").map(Number);
    const aspect = sw > 0 && sh > 0 ? sh / sw : 0.75;
    navigator.mediaDevices?.getUserMedia({ video: { deviceId: { exact: deviceId }, width: { ideal: MAX_W }, height: { ideal: Math.round(MAX_W * aspect) } } })
      .then((s) => {
        if (cancelled) { s.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = s;
        live.watch(s.getVideoTracks()[0] ?? null);
        if (videoRef.current) { videoRef.current.srcObject = s; void videoRef.current.play().catch(() => undefined); }
        setErr(null);
      })
      .catch((e) => setErr(`Live view unavailable: ${e instanceof Error ? e.message : String(e)}`));
    return () => { cancelled = true; stop(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceId, reopen, live.paused]);

  // Send one frame at a time (never a backlog) to the look-only detector.
  useEffect(() => {
    let busy = false;
    const canvas = document.createElement("canvas");
    const id = window.setInterval(() => {
      const v = videoRef.current;
      if (busy || !v || v.videoWidth === 0 || live.paused) return;
      const scale = Math.min(1, MAX_W / v.videoWidth);
      canvas.width = Math.round(v.videoWidth * scale);
      canvas.height = Math.round(v.videoHeight * scale);
      canvas.getContext("2d")?.drawImage(v, 0, 0, canvas.width, canvas.height);
      busy = true;
      canvas.toBlob((blob) => {
        if (!blob) { busy = false; return; }
        api.autocalPreview(blob, { squaresX: board.squaresX, squaresY: board.squaresY, squareMm: board.squareMm, markerMm: board.markerMm, dict: board.dict })
          .then((r) => { setRes(r); setErr(null); })
          .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
          .finally(() => { busy = false; });
      }, "image/jpeg", 0.85);
    }, PERIOD_MS);
    return () => window.clearInterval(id);
  }, [board, live.paused]);

  if (!deviceId) return <div className="warnline">No science camera assigned — set it under Settings → Cameras to see the live view.</div>;
  const pts = res?.points ?? [];
  const chess = pts.filter((p) => p.kind === "corner");
  const marks = pts.filter((p) => p.kind === "marker");
  // The covered area only lines up when the live frame has the photos' aspect ratio (same view).
  const sameShape = !!res && !!covered && Math.abs(res.image_size[1] / res.image_size[0] - covered.size[1] / covered.size[0]) < 0.01;
  const hull = sameShape && covered ? convexHull(scaleOverlay(covered.points, covered.size, res!.image_size)) : undefined;
  return (
    <div className="grid-gap">
      <div style={{ position: "relative", maxWidth: 640, background: "var(--bg-deep)" }}>
        <video ref={videoRef} muted playsInline autoPlay style={{ width: "100%", display: "block" }} />
        {res && (
          <CalibrationOverlay size={res.image_size} chess={chess.map((p) => [p.x, p.y])} chessIds={chess.map((p) => p.id)}
            markers={marks.map((p) => [p.x, p.y])} quads={res.markers} hull={hull} />
        )}
      </div>
      <div className={res?.found ? "okline" : "hint"} style={{ margin: 0 }}>
        {live.paused ? "Live view paused while a full-resolution photo is taken."
          : !res ? "Starting the live view…"
          : res.found ? `Board found: ${pts.length} points (${chess.length} chessboard corners, ${marks.length} marker corners).`
          : "Board not found in the live view."}
        {covered && res && !sameShape && " (The covered-area outline is hidden: the live view's shape differs from the photos'.)"}
      </div>
      {err && <div className="errline" style={{ margin: 0 }}>{err}</div>}
    </div>
  );
}
