import { useEffect, useState } from "react";
import { CameraTiles } from "./CameraTiles.tsx";
import {
  loadOverviewCameraId,
  overviewCandidates,
  saveOverviewCameraId,
  videoInputs,
  type VideoInput,
} from "../lib/webcam.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;

/** Client-side overview camera picker: enumerates the browser's cameras and shows a LIVE tile per
 * real (non-phone) camera so the operator identifies the print-bed camera by sight — the reliable
 * path when two identical ELPs share a label. The pick is saved in the browser (vpi.overviewCameraId)
 * and drives the dock's OverviewCameraPanel. Shared by the quick-start wizard and the guided-setup
 * "identify cameras" step so there is ONE identification path (and no server cv2 stream, which
 * mis-opens the iPhone on macOS). */
export function OverviewPicker({ onPicked }: { onPicked?: (deviceId: string) => void }) {
  const [inputs, setInputs] = useState<VideoInput[]>([]);
  const [pick, setPick] = useState<string | null>(() => loadOverviewCameraId(storage));

  // Enumerate the browser's cameras. Labels need camera permission — if they're blank, prompt once
  // with a throwaway stream, then re-enumerate.
  useEffect(() => {
    const md = typeof navigator !== "undefined" ? navigator.mediaDevices : undefined;
    if (!md?.getUserMedia) return;
    let cancelled = false;
    (async () => {
      try {
        let devs = await md.enumerateDevices();
        if (!videoInputs(devs).some((d) => d.label)) {
          const probe = await md.getUserMedia({ video: true });
          probe.getTracks().forEach((t) => t.stop());
          devs = await md.enumerateDevices();
        }
        if (!cancelled) setInputs(videoInputs(devs));
      } catch {
        // Camera blocked in the browser: fall through to the hint below.
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const onPick = (deviceId: string) => {
    saveOverviewCameraId(storage, deviceId);
    setPick(deviceId);
    onPicked?.(deviceId);
  };

  const cands = overviewCandidates(inputs);
  const tiles = cands.length ? cands : inputs.filter((d) => d.label);
  if (!tiles.length) {
    return (
      <span className="hint" style={{ marginTop: 0 }}>
        No external camera live-view available yet — allow camera access in the browser, or plug in
        the overview camera.
      </span>
    );
  }
  return <CameraTiles candidates={tiles} selectedId={pick} onPick={onPick} />;
}
