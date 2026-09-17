import { OverviewPicker } from "./OverviewPicker.tsx";

/** First-run / re-assign camera wizard (A7 "Camera connection & role persistence").
 *
 *  The two ELPs share a sensor and enumerate with identical labels, so the only reliable way to
 *  tell them apart is by eye. The wizard is therefore ONE list of live tiles (client-side
 *  getUserMedia): click the feed showing the print bed to set the OVERVIEW — saved in the browser
 *  (vpi.overviewCameraId) and shown in the dock. It deliberately does NOT show a second, parallel
 *  server-device list: the browser and the server enumerate the two identical cameras in
 *  independent orders, so a second numbered list would invite a wrong pairing. SCIENCE (bed stills)
 *  is captured server-side and needs the OS device id; assigning it by sight belongs with the
 *  server-side capture-by-UID work (next), where each server device gets its own live preview. */
export function QuickStartVision({ onSkip, onSaved }: {
  onSkip: () => void;
  onSaved: () => void;
}) {
  return (
    <div className="banner quickstart-vision">
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <b>Set up cameras</b>
        <span className="hint" style={{ marginTop: 0 }}>
          Click the camera whose live feed shows the print bed to set it as the overview. The two
          cameras share a name, so the live picture is how you tell them apart.
        </span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
        <b style={{ fontSize: 13 }}>Overview — live wide view</b>
        <OverviewPicker />
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8 }}>
        <b style={{ fontSize: 13 }}>Science camera — bed stills</b>
        <span className="hint" style={{ marginTop: 0 }}>
          Coming in the next update. Because both cameras share a name, the science camera is paired
          to its exact device so the operator records from the right one — set up in the SETUP steps
          once that lands. The overview above is all you need now.
        </span>
      </div>

      <div className="actions">
        <button className="cta primary" onClick={onSaved}>done</button>
        <button className="small" onClick={onSkip}>skip for now</button>
      </div>
    </div>
  );
}
