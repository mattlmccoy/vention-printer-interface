/** Opt-in settings for the OVERVIEW timelapse: capture wide-view frames on a timer during a
 *  recorded print, for a whole-print timelapse of the streaming overview camera (the science
 *  per-layer timelapse is always recorded; this is the extra option). Persisted in localStorage. */

export interface OverviewTimelapseSettings {
  enabled: boolean;
  intervalS: number; // seconds between overview frames while recording
}

const KEY = "vpi.overviewTimelapse";
const DEFAULT: OverviewTimelapseSettings = { enabled: false, intervalS: 3 };

/** Clamp an interval into a sane range (0.5–60 s); junk → the default 3 s. */
export function clampInterval(v: unknown): number {
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return DEFAULT.intervalS;
  return Math.min(60, Math.max(0.5, n));
}

export function loadOverviewTimelapse(storage: Storage | null): OverviewTimelapseSettings {
  try {
    const raw = storage?.getItem(KEY);
    if (!raw) return { ...DEFAULT };
    const p = JSON.parse(raw) as Partial<OverviewTimelapseSettings>;
    return { enabled: !!p.enabled, intervalS: clampInterval(p.intervalS) };
  } catch {
    return { ...DEFAULT };
  }
}

export function saveOverviewTimelapse(storage: Storage | null, s: OverviewTimelapseSettings): void {
  try { storage?.setItem(KEY, JSON.stringify({ enabled: !!s.enabled, intervalS: clampInterval(s.intervalS) })); }
  catch { /* storage disabled */ }
}
