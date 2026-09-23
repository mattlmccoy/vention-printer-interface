// Coordinates camera use on a shared USB bus (lightweight camera mode, camera_mode.ts). Live views
// subscribe; a full-resolution still PAUSES them all first (so their isochronous bandwidth
// reservations are released), opens the camera alone, grabs, closes, and then resumes them — even
// when the grab fails. The order matters: whoever opens first gets the bandwidth.

export interface LiveView { pause(): void; resume(): void }
export interface CameraBus { subscribe(v: LiveView): () => void; pause(): void; resume(): void; paused(): boolean }

export function createCameraBus(): CameraBus {
  const views = new Set<LiveView>();
  let holders = 0;
  const each = (fn: (v: LiveView) => void) => {
    for (const v of [...views]) { try { fn(v); } catch { /* one view must not block the others */ } }
  };
  return {
    subscribe(v) { views.add(v); return () => { views.delete(v); }; },
    pause() { holders += 1; if (holders === 1) each((v) => v.pause()); },
    resume() { if (holders === 0) return; holders -= 1; if (holders === 0) each((v) => v.resume()); },
    paused: () => holders > 0,
  };
}

/** The app-wide bus the live camera views and the capture paths share. */
export const cameraBus = createCameraBus();

export interface FullResDeps {
  bus: CameraBus;
  open: () => Promise<MediaStream>;
  grab: (stream: MediaStream) => Promise<{ blob: Blob | null; attempts: string[] }>;
  /** Time for paused views' devices to actually close (and free their bandwidth) before the open. */
  releaseMs: number;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
}

/** Pause live views → wait for release → open the camera alone → grab → close → resume live views.
 *  Always resumes. Reports how long the open and the whole sequence took (for sizing the print's
 *  capture wait on each machine). */
export async function captureFullResStill(d: FullResDeps): Promise<{ blob: Blob | null; attempts: string[]; openMs: number; totalMs: number }> {
  const sleep = d.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  const now = d.now ?? (() => performance.now());
  const t0 = now();
  let stream: MediaStream | null = null;
  let openMs = 0;
  d.bus.pause();
  try {
    if (d.releaseMs > 0) await sleep(d.releaseMs);
    const tOpen = now();
    try {
      stream = await d.open();
    } catch (e) {
      return { blob: null, attempts: [`open full-res: ${e instanceof Error ? e.message : String(e)}`], openMs: now() - tOpen, totalMs: now() - t0 };
    }
    openMs = now() - tOpen;
    const r = await d.grab(stream);
    return { ...r, openMs, totalMs: now() - t0 };
  } finally {
    stream?.getTracks().forEach((t) => t.stop());
    d.bus.resume();
  }
}
