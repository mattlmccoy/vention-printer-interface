// Persistent capture settings for the OVERVIEW camera (client-side getUserMedia).
//
// Resolution + frame rate are chosen up front and applied when the stream opens (a resolution change
// needs a fresh stream — a "reload"); the manual bag (exposure, etc.) is applied live via
// applyConstraints. Persisted so the dock live view and the setup page agree, and the choice sticks
// across reloads. Default is 4K @ 30 — the sharpest the ELP streams over USB3 (20MP@30 isn't
// streamable; 4K@30 usually is, else the browser negotiates down).

export interface OverviewSettings {
  resolution: string; // "WIDTHxHEIGHT", e.g. "3840x2160"
  frameRate: number;
  manual: Record<string, number>; // live applyConstraints controls (exposureTime, brightness, …)
}

export const RESOLUTIONS: { key: string; label: string; width: number; height: number }[] = [
  { key: "3840x2160", label: "4K · 3840×2160", width: 3840, height: 2160 },
  { key: "1920x1080", label: "1080p · 1920×1080", width: 1920, height: 1080 },
  { key: "1280x720", label: "720p · 1280×720", width: 1280, height: 720 },
];

export const DEFAULT_OVERVIEW_SETTINGS: OverviewSettings = {
  resolution: "3840x2160",
  frameRate: 30,
  manual: {},
};

/** The two client-side camera roles that carry their own live-tuned settings. */
export type SettingsRole = "overview" | "science";
const KEYS: Record<SettingsRole, string> = {
  overview: "vpi.overviewSettings",
  science: "vpi.scienceSettings",
};

/** Width/height for a resolution key; unknown keys fall back to 4K (the default we always request). */
export function resolutionWH(key: string): { width: number; height: number } {
  const r = RESOLUTIONS.find((x) => x.key === key);
  return r ? { width: r.width, height: r.height } : { width: 3840, height: 2160 };
}

/** getUserMedia video constraints for a device at these settings (ideal, so the browser negotiates
 *  down when the camera/hub can't do it). */
export function videoConstraints(deviceId: string, s: OverviewSettings): MediaTrackConstraints {
  const { width, height } = resolutionWH(s.resolution);
  return {
    deviceId: { exact: deviceId },
    width: { ideal: width },
    height: { ideal: height },
    frameRate: { ideal: s.frameRate },
  };
}

/** Load a role's settings, merged over the defaults (a partial saved blob keeps default fields). */
export function loadCameraSettings(storage: Storage | null, role: SettingsRole): OverviewSettings {
  try {
    const raw = storage?.getItem(KEYS[role]);
    if (!raw) return { ...DEFAULT_OVERVIEW_SETTINGS, manual: {} };
    const p = JSON.parse(raw) as Partial<OverviewSettings>;
    return {
      resolution: typeof p.resolution === "string" ? p.resolution : DEFAULT_OVERVIEW_SETTINGS.resolution,
      frameRate: typeof p.frameRate === "number" ? p.frameRate : DEFAULT_OVERVIEW_SETTINGS.frameRate,
      manual: p.manual && typeof p.manual === "object" ? p.manual : {},
    };
  } catch {
    return { ...DEFAULT_OVERVIEW_SETTINGS, manual: {} };
  }
}

export function saveCameraSettings(storage: Storage | null, role: SettingsRole, s: OverviewSettings): void {
  try {
    storage?.setItem(KEYS[role], JSON.stringify(s));
  } catch {
    /* storage disabled: settings just aren't remembered */
  }
}

// Overview aliases — the dock live view reads/writes the overview role.
export function loadOverviewSettings(storage: Storage | null): OverviewSettings {
  return loadCameraSettings(storage, "overview");
}
export function saveOverviewSettings(storage: Storage | null, s: OverviewSettings): void {
  saveCameraSettings(storage, "overview", s);
}
