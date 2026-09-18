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

export interface Resolution { key: string; label: string; width: number; height: number }

/** The two client-side camera roles that carry their own live-tuned settings. */
export type SettingsRole = "overview" | "science";

// Resolutions offered PER ROLE. The overview is a live wide view (tops out at streamable 4K). The
// SCIENCE camera shoots stills, so it also offers extra-high resolutions up to its native 20 MP
// (5120×3840) — gated by frame rate (the capability sliders show the fps range each res supports;
// at 20 MP that's very low). A 20 MP live preview may not stream, but the value is used for capture.
const OVERVIEW_RES: Resolution[] = [
  { key: "3840x2160", label: "4K · 3840×2160", width: 3840, height: 2160 },
  { key: "1920x1080", label: "1080p · 1920×1080", width: 1920, height: 1080 },
  { key: "1280x720", label: "720p · 1280×720", width: 1280, height: 720 },
];
const SCIENCE_RES: Resolution[] = [
  { key: "5120x3840", label: "20MP · 5120×3840 (stills)", width: 5120, height: 3840 },
  { key: "3840x2160", label: "4K · 3840×2160", width: 3840, height: 2160 },
  { key: "2560x1440", label: "QHD · 2560×1440", width: 2560, height: 1440 },
  { key: "1920x1080", label: "1080p · 1920×1080", width: 1920, height: 1080 },
];
const RESOLUTIONS_BY_ROLE: Record<SettingsRole, Resolution[]> = {
  overview: OVERVIEW_RES,
  science: SCIENCE_RES,
};

/** The resolution options for a role. */
export function resolutionsFor(role: SettingsRole): Resolution[] {
  return RESOLUTIONS_BY_ROLE[role];
}

/** Back-compat: the overview resolution list. */
export const RESOLUTIONS: Resolution[] = OVERVIEW_RES;

/** Per-role default settings. Overview + science both default to a STREAMABLE 4K@30 so the live
 *  preview works; 20 MP is opt-in for the science camera (a still capture size). */
export function defaultSettingsFor(role: SettingsRole): OverviewSettings {
  void role; // both roles default to 4K@30 today; kept role-typed for future per-role defaults
  return { resolution: "3840x2160", frameRate: 30, manual: {} };
}

export const DEFAULT_OVERVIEW_SETTINGS: OverviewSettings = defaultSettingsFor("overview");

const KEYS: Record<SettingsRole, string> = {
  overview: "vpi.overviewSettings",
  science: "vpi.scienceSettings",
};

/** Width/height for a "WIDTHxHEIGHT" key (parsed, so any listed or custom size works); junk falls
 *  back to 4K. */
export function resolutionWH(key: string): { width: number; height: number } {
  const m = /^(\d+)x(\d+)$/.exec(key);
  if (m) return { width: Number(m[1]), height: Number(m[2]) };
  return { width: 3840, height: 2160 };
}

/** The resolution to actually OPEN the live preview at. 20 MP (and anything above ~4K) can't stream
 *  over USB — only shoot a still — so a preview request at that size fails and the camera never goes
 *  live, hiding every capability slider (exposure!). Cap the preview at 4K; the snapshot resolution
 *  (the dropdown / server setting) stays independent and can still be full-res. */
export function streamableRes(key: string): string {
  const { width, height } = resolutionWH(key);
  if (width * height > 8_300_000) return "3840x2160"; // > 4K → fall back to a streamable 4K preview
  return `${width}x${height}`;
}

/** getUserMedia video constraints for a device at these settings (ideal, so the browser negotiates
 *  down when the camera/hub can't do it). The preview is capped to a streamable size so the camera
 *  opens even when the chosen snapshot resolution is a still-only 20 MP. */
export function videoConstraints(deviceId: string, s: OverviewSettings): MediaTrackConstraints {
  const { width, height } = resolutionWH(streamableRes(s.resolution));
  return {
    deviceId: { exact: deviceId },
    width: { ideal: width },
    height: { ideal: height },
    frameRate: { ideal: s.frameRate },
  };
}

/** Load a role's settings, merged over that role's defaults (a partial saved blob keeps defaults). */
export function loadCameraSettings(storage: Storage | null, role: SettingsRole): OverviewSettings {
  const def = defaultSettingsFor(role);
  try {
    const raw = storage?.getItem(KEYS[role]);
    if (!raw) return def;
    const p = JSON.parse(raw) as Partial<OverviewSettings>;
    return {
      resolution: typeof p.resolution === "string" ? p.resolution : def.resolution,
      frameRate: typeof p.frameRate === "number" ? p.frameRate : def.frameRate,
      manual: p.manual && typeof p.manual === "object" ? p.manual : {},
    };
  } catch {
    return def;
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
