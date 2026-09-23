// Glue that keeps the browser's camera ignore set in step with the operator and with open pickers.
// The pure rules live in camera_ignore.ts (unit-tested); this file only does the I/O: fetch the
// server's ignored names, enumerate cameras, scrub stale saved ids, and tell pickers to refresh.
import { useEffect, useState } from "react";
import { api } from "./api.ts";
import {
  IGNORE_CHANGED_EVENT,
  ignoreDevice,
  loadIgnoreSet,
  notifyIgnoreChanged,
  saveIgnoredNames,
  scrubHiddenSelections,
} from "./camera_ignore.ts";
import { allVideoInputs } from "./webcam.ts";

/** Cache the server's ignored names (when given), clear saved role/live-feed ids that point at a
 *  hidden camera, then tell open pickers to re-enumerate. `names` undefined = keep the cache
 *  (operator unreachable, or an older operator that does not send names). */
export async function applyIgnoredNames(storage: Storage | null, names: string[] | undefined): Promise<void> {
  if (Array.isArray(names)) saveIgnoredNames(storage, names);
  try {
    const md = typeof navigator !== "undefined" ? navigator.mediaDevices : undefined;
    if (md?.enumerateDevices) {
      const devs = await md.enumerateDevices();
      scrubHiddenSelections(storage, allVideoInputs(devs), loadIgnoreSet(storage));
    }
  } catch {
    /* enumeration blocked: pickers still filter by the cached set */
  }
  notifyIgnoreChanged();
}

/** Pull the ignore list from the operator and apply it (app start / reconnect). */
export async function syncCameraIgnore(storage: Storage | null): Promise<void> {
  let names: string[] | undefined;
  try {
    names = (await api.ignoredCameras()).names;
  } catch {
    names = undefined;
  }
  await applyIgnoredNames(storage, names);
}

/** Hide one camera in THIS browser by its deviceId (the only way to hide one of two identical
 *  ELPs, whose labels match), dropping any saved role / live-feed selection of it. */
export function ignoreCameraHere(storage: Storage | null, deviceId: string): void {
  ignoreDevice(storage, deviceId);
  scrubHiddenSelections(storage, [], loadIgnoreSet(storage));
  notifyIgnoreChanged();
}

/** A counter that ticks whenever the ignore set changes — add it to a picker's enumerate deps. */
export function useIgnoreVersion(): number {
  const [n, setN] = useState(0);
  useEffect(() => {
    const bump = () => setN((v) => v + 1);
    window.addEventListener(IGNORE_CHANGED_EVENT, bump);
    return () => window.removeEventListener(IGNORE_CHANGED_EVENT, bump);
  }, []);
  return n;
}
