import { CameraRoleAssigner } from "./CameraRoleAssigner.tsx";

/** First-run / re-assign camera wizard (A7 "Camera connection & role persistence").
 *
 *  The two ELPs share a sensor and enumerate with identical labels, so the only reliable way to
 *  tell them apart is by eye. The wizard is ONE list of live tiles (client-side getUserMedia): each
 *  tile shows its live feed and a role dropdown, so the operator assigns BOTH overview and science
 *  by sight. Overview drives the dock live view immediately (vpi.overviewCameraId); science is
 *  remembered (vpi.scienceCameraId) — its server-side recording pairs to the device in the
 *  capture-by-UID work. No second server-device list: the browser and server enumerate the two
 *  identical cameras in independent orders, so a parallel list would invite a wrong pairing. */
export function QuickStartVision({ onSkip, onSaved }: {
  onSkip: () => void;
  onSaved: () => void;
}) {
  return (
    <div className="banner quickstart-vision">
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <b>Set up cameras</b>
        <span className="hint" style={{ marginTop: 0 }}>
          Assign each camera by its live picture — the two share a name, so the feed is how you tell
          them apart. Set one as overview (the dock’s wide live view) and one as science (bed stills).
        </span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
        <CameraRoleAssigner />
      </div>

      <span className="hint" style={{ marginTop: 0 }}>
        Overview goes live in the dock now. Science recording (bed stills during a print) activates
        with the capture-by-device update — your assignment here is remembered for it.
      </span>

      <div className="actions">
        <button className="cta primary" onClick={onSaved}>done</button>
        <button className="small" onClick={onSkip}>skip for now</button>
      </div>
    </div>
  );
}
