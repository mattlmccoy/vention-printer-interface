// Client-side overview camera selection.
//
// The overview LIVE VIEW is rendered in the browser via getUserMedia, not the server-side MJPEG
// stream. On macOS the server's cv2.VideoCapture opens cameras by an index whose order does NOT
// match our enumeration, so it can grab the wrong physical camera (2026-09-17: it kept opening the
// iPhone Continuity camera and labelling it the 20MP ELP). The browser enumerates cameras by their
// real label/deviceId, so selecting the ELP here is reliable. This module is the pure selection +
// persistence logic; the getUserMedia/<video> wiring lives in the component.

import { isIgnoredInput, loadIgnoreSet, type IgnoreSet } from "./camera_ignore.ts";

const OVERVIEW_CAM_KEY = "vpi.overviewCameraId";
const NO_IGNORE: IgnoreSet = { deviceIds: [], names: [] };

function defaultStorage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export interface VideoInput {
  deviceId: string;
  label: string;
}

/** EVERY video input from `enumerateDevices()`, ignored ones included — only for the Settings
 *  camera inventory, which must show hidden cameras so they can be un-ignored. */
export function allVideoInputs(devices: { kind: string; deviceId: string; label: string }[]): VideoInput[] {
  return devices
    .filter((d) => d.kind === "videoinput")
    .map((d) => ({ deviceId: d.deviceId, label: d.label }));
}

/** The video inputs a picker may show: `enumerateDevices()` minus every camera on the ignore list
 *  (Settings → Camera inventory). Defaults to the ignore set saved in this browser, so every caller
 *  filters without having to remember to. */
export function videoInputs(
  devices: { kind: string; deviceId: string; label: string }[],
  ignore: IgnoreSet = loadIgnoreSet(defaultStorage()),
): VideoInput[] {
  return allVideoInputs(devices).filter((d) => !isIgnoredInput(d, ignore));
}

/** True for a built-in / phone / virtual camera we must never auto-pick for the overview (the
 * operator's real cameras are external USB — the 20MP ELPs). Matched on the browser label. */
export function isBuiltinOrPhoneLabel(label: string): boolean {
  const l = label.toLowerCase();
  return (
    l.includes("facetime") ||
    l.includes("iphone") ||
    l.includes("continuity") ||
    l.includes("desk view") ||
    l.includes("ipad") ||
    l.includes("macbook") || // Apple-silicon built-in: "MacBook Pro Camera"
    l.includes("built-in") ||
    l.includes("integrated") // Windows laptops: "Integrated Camera"
  );
}

/** Choose the overview camera's deviceId, or null when the operator must pick one:
 *  1. the saved deviceId, if that camera is still plugged in and is neither built-in/phone nor
 *     ignored (a stale save from before it was ignored must not win);
 *  2. else a camera whose label matches `nameHint` (the assigned overview device's name) and is
 *     not a built-in/phone camera;
 *  3. else the ONLY non-built-in/phone camera, if exactly one exists;
 *  4. else null → show the picker (ambiguous; never guess between real cameras). */
export function pickOverviewDeviceId(
  inputs: VideoInput[],
  savedId: string | null,
  nameHint: string | null,
  ignore: IgnoreSet = NO_IGNORE,
): string | null {
  const usable = inputs.filter(
    (d) => !isIgnoredInput(d, ignore) && !(d.label && isBuiltinOrPhoneLabel(d.label)),
  );
  if (savedId && usable.some((d) => d.deviceId === savedId)) return savedId;
  const real = usable.filter((d) => d.label);
  if (nameHint) {
    const hint = nameHint.toLowerCase();
    const byName = real.find((d) => d.label.toLowerCase().includes(hint));
    if (byName) return byName.deviceId;
  }
  if (real.length === 1) return real[0].deviceId;
  return null;
}

/** The real cameras to show as live preview tiles when the operator must identify one by sight:
 *  every labelled, non-built-in/phone camera, in enumeration order. With two identical ELPs this
 *  returns both (their labels match, so only a live feed tells them apart); with one real camera it
 *  still returns it so the tile confirms which physical device it is. Blank-label devices are
 *  dropped — with no label they can't be named or reliably previewed. */
export function overviewCandidates(inputs: VideoInput[]): VideoInput[] {
  return inputs.filter((d) => d.label && !isBuiltinOrPhoneLabel(d.label));
}

/** A camera plus a display name that stays unique when two devices share a label. */
export interface LabeledCamera extends VideoInput {
  display: string;
}

/** Give each camera a display name, appending " #n" ONLY to labels that collide (two identical
 *  ELPs -> "…Camera #1" / "…Camera #2"); unique labels are left untouched. Ordinals count within
 *  the same label, in list order, so a tile's number is stable for a given enumeration. */
export function labelCandidates(cams: VideoInput[]): LabeledCamera[] {
  const counts = new Map<string, number>();
  for (const c of cams) counts.set(c.label, (counts.get(c.label) ?? 0) + 1);
  const seen = new Map<string, number>();
  return cams.map((c) => {
    if ((counts.get(c.label) ?? 0) <= 1) return { ...c, display: c.label };
    const n = (seen.get(c.label) ?? 0) + 1;
    seen.set(c.label, n);
    return { ...c, display: `${c.label} #${n}` };
  });
}

export function loadOverviewCameraId(storage: Storage | null): string | null {
  try {
    return storage?.getItem(OVERVIEW_CAM_KEY) || null;
  } catch {
    return null;
  }
}

export function saveOverviewCameraId(storage: Storage | null, deviceId: string): void {
  try {
    storage?.setItem(OVERVIEW_CAM_KEY, deviceId);
  } catch {
    /* private mode / disabled storage: selection just isn't remembered */
  }
}

/** True when the browser lists camera(s) but hides every label — i.e. this site has never been
 *  granted camera access (browsers withhold labels, and Chrome also deviceIds, until then). The UI
 *  must then offer an explicit, user-clicked grant: nothing else ever triggers the prompt (we avoid
 *  an automatic getUserMedia({video:true}) because on macOS it can wake an iPhone Continuity
 *  Camera). A fresh Windows browser hits exactly this, which left the camera pickers empty. */
export function needsCameraPermission(devices: { kind: string; label: string; deviceId?: string }[]): boolean {
  const cams = devices.filter((d) => d.kind === "videoinput");
  return cams.length > 0 && cams.every((d) => !d.label);
}

/** Ask for camera access (only ever call this from a user click). Opens the default camera just
 *  long enough to get the grant, then stops it; afterwards enumerateDevices returns real labels. */
export async function requestCameraPermission(md: MediaDevices): Promise<void> {
  const stream = await md.getUserMedia({ video: true });
  stream.getTracks().forEach((t) => t.stop());
}

/** Actionable text for a getUserMedia failure, so a tile says WHY it is empty instead of a silent
 *  black box. Windows specifics: a system-wide privacy switch can block every desktop app (the
 *  browser included) while the built-in Camera app still works, and only one app can hold a camera
 *  at a time. */
export function cameraErrorMessage(err: unknown): string {
  const name = err && typeof err === "object" && "name" in err ? String((err as { name: unknown }).name) : "";
  const message = err instanceof Error ? err.message : "";
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
    case "PermissionDeniedError":
      return "Camera access is blocked. Allow the camera for this site (address-bar camera icon). "
        + "On Windows also check Settings → Privacy & security → Camera → "
        + "“Let desktop apps access your camera”.";
    case "NotReadableError":
    case "TrackStartError":
      return "Camera is in use by another app — close the Camera app / Teams / Zoom (or another "
        + "browser tab) and retry. Windows lets only one app hold a camera at a time.";
    case "NotFoundError":
    case "DevicesNotFoundError":
      return "Camera not found — it may have been unplugged. Replug it and retry.";
    case "OverconstrainedError":
    case "ConstraintNotSatisfiedError":
      return "Camera not available at the requested resolution/frame rate — retry, or lower the "
        + "camera settings.";
    case "AbortError":
      return "Camera failed to start — unplug and replug it, then retry.";
    default:
      return name ? `Camera error: ${name}${message ? `: ${message}` : ""}` : "Camera error — retry.";
  }
}
