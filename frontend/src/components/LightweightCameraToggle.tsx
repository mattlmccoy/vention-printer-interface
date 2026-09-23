import { useState } from "react";
import { cameraBus } from "../lib/camera_bus.ts";
import { LIGHT_LIVE, lightweightDefault, lightweightEnabled, saveLightweight } from "../lib/camera_mode.ts";
import { Toggle } from "./Toggle.tsx";

/** Settings → Camera settings: the lightweight camera mode switch (camera_mode.ts). Per browser —
 *  it describes THIS machine's USB path. Flipping it reopens every live view at the new size. */
export function LightweightCameraToggle() {
  const [on, setOn] = useState(() => lightweightEnabled());
  const isDefault = on === lightweightDefault(typeof navigator === "undefined" ? "" : navigator.userAgent);
  const change = (next: boolean) => {
    saveLightweight(typeof localStorage === "undefined" ? null : localStorage, next);
    setOn(next);
    cameraBus.pause(); // stop every live view…
    cameraBus.resume(); // …and reopen it with the new constraints
  };
  return (
    <div className="grid-gap" style={{ gap: 6 }}>
      <label className="row" style={{ gap: 10, alignItems: "center" }}>
        <Toggle label="lightweight camera mode" checked={on} onChange={change} />
        <span className="hint" style={{ marginTop: 0 }}>{isDefault ? "default for this computer" : "changed from this computer's default"}</span>
      </label>
      <span className="hint" style={{ marginTop: 0 }}>
        For cameras that share a slow USB path (e.g. a hub behind a USB-Ethernet adapter): live views run at {LIGHT_LIVE.width}×{LIGHT_LIVE.height} @ {LIGHT_LIVE.frameRate} fps, and every science still — during prints and Camera Studio snapshots — is taken at full resolution, lossless, with that camera alone (other views pause for a moment; the print waits for the still). Off: full-quality live streams. On by default on Windows.
      </span>
    </div>
  );
}
