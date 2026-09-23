// Camera ignore list, browser side (Settings → Camera inventory).
//
// Two ways a camera gets ignored, because the browser and the server name cameras differently:
//  - by NAME: the server keeps the ignore list by macOS unique id, which the browser can't see.
//    GET /api/vision/ignored-cameras returns the ignored cameras' names (only names no
//    non-ignored camera shares), cached here so every picker can filter synchronously. A browser
//    label can carry a suffix like " (32e4:9230)", so a label matches when it CONTAINS the name.
//  - by deviceId: stored in this browser only. The only way to hide ONE of two identical ELPs,
//    whose labels are the same.
// Every picker applies this through videoInputs() (webcam.ts); scrubHiddenSelections() clears
// saved role / live-feed ids that point at a hidden camera, so no saved-id consumer opens it.

import { isBuiltinOrPhoneLabel, labelCandidates, type VideoInput } from "./webcam.ts";

export interface IgnoreSet {
  deviceIds: string[];
  names: string[];
}

const IGNORED_IDS_KEY = "vpi.ignoredCameraDeviceIds";
const IGNORED_NAMES_KEY = "vpi.ignoredCameraNames";
/** Saved-id keys a hidden camera must not stay in (camera_roles.ts + live_feed.ts). */
const SELECTION_KEYS = ["vpi.overviewCameraId", "vpi.scienceCameraId", "vpi.liveFeedCameraId"];
/** Fired on window after the ignore set changes, so open pickers re-enumerate. */
export const IGNORE_CHANGED_EVENT = "vpi:camera-ignore-changed";

function readList(storage: Storage | null, key: string): string[] {
  try {
    const raw = storage?.getItem(key);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string" && !!x) : [];
  } catch {
    return [];
  }
}

function writeList(storage: Storage | null, key: string, list: string[]): void {
  try {
    storage?.setItem(key, JSON.stringify([...new Set(list.filter(Boolean))]));
  } catch {
    /* storage disabled: the ignore lasts for this page only */
  }
}

export function loadIgnoreSet(storage: Storage | null): IgnoreSet {
  return { deviceIds: readList(storage, IGNORED_IDS_KEY), names: readList(storage, IGNORED_NAMES_KEY) };
}

/** Cache the server's ignored-camera names (from GET /api/vision/ignored-cameras). */
export function saveIgnoredNames(storage: Storage | null, names: string[]): void {
  writeList(storage, IGNORED_NAMES_KEY, names);
}

export function ignoreDevice(storage: Storage | null, deviceId: string): void {
  writeList(storage, IGNORED_IDS_KEY, [...readList(storage, IGNORED_IDS_KEY), deviceId]);
}

export function unignoreDevice(storage: Storage | null, deviceId: string): void {
  writeList(storage, IGNORED_IDS_KEY, readList(storage, IGNORED_IDS_KEY).filter((d) => d !== deviceId));
}

export function isIgnoredInput(input: VideoInput, ignore: IgnoreSet): boolean {
  if (ignore.deviceIds.includes(input.deviceId)) return true;
  const label = input.label.toLowerCase();
  return !!label && ignore.names.some((n) => !!n && label.includes(n.toLowerCase()));
}

/** Why a camera is kept out of the pickers: the operator ignored it, or it is a built-in/phone
 *  camera (never a print camera). null = visible. */
export function hiddenReason(input: VideoInput, ignore: IgnoreSet): "ignored" | "built-in" | null {
  if (isIgnoredInput(input, ignore)) return "ignored";
  if (input.label && isBuiltinOrPhoneLabel(input.label)) return "built-in";
  return null;
}

/** One row of the Settings camera inventory: every camera, with why it is hidden (null = shown in
 *  the pickers) and whether THIS browser hid it by deviceId (only those can be un-ignored here;
 *  a name ignore is undone in the server list). Identical labels are numbered #1/#2. */
export interface InventoryRow {
  deviceId: string;
  label: string;
  display: string;
  reason: "ignored" | "built-in" | null;
  ignoredHere: boolean;
}

export function inventoryRows(inputs: VideoInput[], ignore: IgnoreSet): InventoryRow[] {
  return labelCandidates(inputs).map((c) => ({
    deviceId: c.deviceId,
    label: c.label,
    display: c.display,
    reason: hiddenReason(c, ignore),
    ignoredHere: ignore.deviceIds.includes(c.deviceId),
  }));
}

/** Remove saved role / live-feed ids that point at a hidden camera. `inputs` is the UNFILTERED
 *  enumeration (labels are needed to match names). An id not enumerated right now is kept unless
 *  its deviceId is ignored: an unplugged camera's selection must survive a replug. Returns the
 *  keys cleared. */
export function scrubHiddenSelections(storage: Storage | null, inputs: VideoInput[], ignore: IgnoreSet): string[] {
  const cleared: string[] = [];
  for (const key of SELECTION_KEYS) {
    let id: string | null = null;
    try { id = storage?.getItem(key) || null; } catch { id = null; }
    if (!id) continue;
    const input = inputs.find((d) => d.deviceId === id);
    const hidden = ignore.deviceIds.includes(id) || (input !== undefined && hiddenReason(input, ignore) !== null);
    if (!hidden) continue;
    try { storage?.removeItem(key); cleared.push(key); } catch { /* storage disabled */ }
  }
  return cleared;
}

/** Tell open pickers to re-read the ignore set. */
export function notifyIgnoreChanged(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(IGNORE_CHANGED_EVENT));
}
