import { useEffect, useState } from "react";
import { api } from "../lib/api.ts";
import { calibrationSizeWarning } from "../lib/calib_size.ts";
import { loadCameraSettings } from "../lib/overview_settings.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;

/** Which photo size the loaded calibration holds at, and a warning when the science camera's
 *  resolution setting no longer matches it (the operator stores such stills but does not measure
 *  them). `refreshKey` re-reads the operator after a new calibration is finalized. */
export function CalibrationSizeNote({ refreshKey = 0 }: { refreshKey?: number }) {
  const [size, setSize] = useState<[number, number] | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    api.visionStatus()
      .then((s) => { if (live) setSize(s.calibration_image_size ?? null); })
      .catch(() => { if (live) setSize(undefined); });
    return () => { live = false; };
  }, [refreshKey]);
  if (size === undefined) return null; // operator unreachable: say nothing rather than guess
  const resolution = loadCameraSettings(storage, "science").resolution;
  const warning = calibrationSizeWarning(resolution, size);
  if (warning) return <div className="warnline">{warning}</div>;
  if (!size) return <div className="hint">No calibration loaded yet.</div>;
  return <div className="hint">Calibration holds for {size[0]}×{size[1]} science photos — the camera is set to match.</div>;
}
