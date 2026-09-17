// Live camera controls from a MediaStreamTrack's real capabilities.
//
// The overview runs client-side (getUserMedia), so we can read the camera's actual capability
// ranges — track.getCapabilities() — and expose ONLY the controls the browser/camera really
// supports, each as a slider with the correct min/max/step (no more guessing the scale). Changes
// apply live via track.applyConstraints(); a few (resolution) want a fresh stream (reload).

export interface NumericControl {
  key: string; // the MediaTrackConstraint key, e.g. "frameRate", "exposureTime", "brightness"
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
}

// Numeric camera controls we surface, in display order. Only those the device reports (with a real
// numeric min/max) appear — so exposure only shows on cameras/browsers that expose it.
const NUMERIC: { key: string; label: string }[] = [
  { key: "frameRate", label: "fps" },
  { key: "exposureTime", label: "exposure" },
  { key: "exposureCompensation", label: "exposure comp" },
  { key: "brightness", label: "brightness" },
  { key: "contrast", label: "contrast" },
  { key: "saturation", label: "saturation" },
  { key: "sharpness", label: "sharpness" },
  { key: "colorTemperature", label: "white balance" },
  { key: "focusDistance", label: "focus" },
  { key: "zoom", label: "zoom (optical)" },
];

type Caps = Record<string, unknown>;
type Settings = Record<string, unknown>;

function range(v: unknown): { min: number; max: number; step: number } | null {
  if (!v || typeof v !== "object") return null;
  const r = v as { min?: number; max?: number; step?: number };
  if (typeof r.min !== "number" || typeof r.max !== "number" || r.max <= r.min) return null;
  return { min: r.min, max: r.max, step: typeof r.step === "number" && r.step > 0 ? r.step : 0 };
}

/** The sliders to show for this track, from its capabilities + current settings. Chooses a sane
 * step when the device doesn't report one (~100 divisions of the range). */
export function numericControls(caps: Caps, settings: Settings): NumericControl[] {
  const out: NumericControl[] = [];
  for (const { key, label } of NUMERIC) {
    const r = range(caps[key]);
    if (!r) continue;
    const step = r.step || Math.max((r.max - r.min) / 100, 1e-6);
    const cur = typeof settings[key] === "number" ? (settings[key] as number) : r.min;
    out.push({ key, label, min: r.min, max: r.max, step, value: Math.min(r.max, Math.max(r.min, cur)) });
  }
  return out;
}

/** The applyConstraints() payload to set one control live. Exposure/focus/white-balance are manual
 * controls, so we flip their *mode* to manual in the same advanced constraint; frameRate is a plain
 * top-level constraint. */
export function applyPayload(key: string, value: number): MediaTrackConstraints {
  if (key === "frameRate") return { frameRate: value };
  const modeFor: Record<string, string> = {
    exposureTime: "exposureMode",
    focusDistance: "focusMode",
    colorTemperature: "whiteBalanceMode",
  };
  const adv: Record<string, unknown> = { [key]: value };
  if (modeFor[key]) adv[modeFor[key]] = "manual";
  return { advanced: [adv] } as MediaTrackConstraints;
}
