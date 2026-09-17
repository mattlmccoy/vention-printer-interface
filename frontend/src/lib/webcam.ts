// Client-side overview camera selection.
//
// The overview LIVE VIEW is rendered in the browser via getUserMedia, not the server-side MJPEG
// stream. On macOS the server's cv2.VideoCapture opens cameras by an index whose order does NOT
// match our enumeration, so it can grab the wrong physical camera (2026-09-17: it kept opening the
// iPhone Continuity camera and labelling it the 20MP ELP). The browser enumerates cameras by their
// real label/deviceId, so selecting the ELP here is reliable. This module is the pure selection +
// persistence logic; the getUserMedia/<video> wiring lives in the component.

const OVERVIEW_CAM_KEY = "vpi.overviewCameraId";

export interface VideoInput {
  deviceId: string;
  label: string;
}

/** The video inputs from `enumerateDevices()`, as our minimal shape. */
export function videoInputs(devices: { kind: string; deviceId: string; label: string }[]): VideoInput[] {
  return devices
    .filter((d) => d.kind === "videoinput")
    .map((d) => ({ deviceId: d.deviceId, label: d.label }));
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
    l.includes("ipad")
  );
}

/** Choose the overview camera's deviceId, or null when the operator must pick one:
 *  1. the saved deviceId, if that camera is still plugged in;
 *  2. else a camera whose label matches `nameHint` (the assigned overview device's name) and is
 *     not a built-in/phone camera;
 *  3. else the ONLY non-built-in/phone camera, if exactly one exists;
 *  4. else null → show the picker (ambiguous; never guess between real cameras). */
export function pickOverviewDeviceId(
  inputs: VideoInput[],
  savedId: string | null,
  nameHint: string | null,
): string | null {
  if (savedId && inputs.some((d) => d.deviceId === savedId)) return savedId;
  const real = inputs.filter((d) => d.label && !isBuiltinOrPhoneLabel(d.label));
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
