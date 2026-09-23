import { useState } from "react";
import { cameraErrorMessage, needsCameraPermission, requestCameraPermission } from "../lib/webcam.ts";

/** Shown in place of an empty camera picker. Explains WHY no cameras are listed and, when the
 *  browser is hiding them for lack of permission, offers an explicit grant. The grant only ever runs
 *  from this user click — never automatically — because on macOS an unprompted
 *  getUserMedia({video:true}) can wake an iPhone Continuity Camera. On a fresh Windows browser this
 *  button is the only way to unlock the camera list. */
export function CameraAccessPrompt({
  devices,
  onGranted,
}: {
  devices: { kind: string; label: string }[];
  onGranted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const md = typeof navigator !== "undefined" ? navigator.mediaDevices : undefined;
  const hidden = needsCameraPermission(devices);
  const anyCam = devices.some((d) => d.kind === "videoinput");
  // Offer the grant when labels are hidden, and also when the browser lists no cameras at all (some
  // browsers hide the whole list until permission) — a failure then reports its exact reason.
  const showGrant = hidden || !anyCam;

  const grant = async () => {
    if (!md?.getUserMedia) return;
    setBusy(true);
    setError("");
    try {
      await requestCameraPermission(md);
      onGranted();
    } catch (e) {
      setError(cameraErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const why = hidden
    ? "The browser is hiding the cameras until this site is allowed to use them."
    : anyCam
      ? "No external camera found — only phone/built-in cameras are visible."
      : "The browser can't see any cameras. Check the USB connection; on Windows also check "
        + "Settings → Privacy & security → Camera → “Let desktop apps access your camera”.";

  return (
    <div className="cam-access-prompt" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span className="hint" style={{ marginTop: 0 }}>{why}</span>
      {showGrant && (
        <button
          className="small"
          style={{ alignSelf: "flex-start" }}
          disabled={busy || !md?.getUserMedia}
          onClick={grant}
        >
          {busy ? "waiting for permission…" : "Grant camera access"}
        </button>
      )}
      {error && (
        <span className="hint" role="alert" style={{ marginTop: 0, color: "var(--warn)" }}>{error}</span>
      )}
    </div>
  );
}
