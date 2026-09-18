/** User-visible console changelog (#16). Newest release first. Versions track the single-source
 *  backend __version__ (baked into the build as __APP_VERSION__ and used by UpdateBanner): when you
 *  ship a meaningful change, bump backend __version__ AND add the matching entry at the TOP here, so
 *  the version the user sees actually moves — not only when the operator is separately updated. */

export interface Release {
  version: string;
  date: string; // ISO yyyy-mm-dd
  changes: string[];
}

export const CHANGELOG: Release[] = [
  {
    version: "0.10.1",
    date: "2026-09-18",
    changes: [
      "Science layer captures now fall back to the operator when the browser camera opens without delivering a usable frame.",
      "Camera Studio and Setup verify playable video and use bandwidth-safe previews without changing saved science-capture settings.",
      "The dock live-feed selection no longer overwrites overview/science camera assignments or duplicates the science feed in Camera Studio.",
    ],
  },
  {
    version: "0.10.0",
    date: "2026-09-18",
    changes: [
      "Controls page: axes laid out as a 2×2 board — printhead / recoater on top, feed / build piston below.",
      "Camera Studio enlarged to show both feeds much larger; its snapshot is now a lossless frame grab.",
      "Camera Settings restored: per-camera pixel format (YUY2 = uncompressed/lossless, or MJPG), resolution, fps, and exposure, with the camera model shown.",
      "Science stills captured losslessly for layerwise CAD comparison; a unique-id-bound server capture path keeps the correct camera shooting.",
      "Timelapse from the overview (streaming) camera, in addition to the science camera.",
      "Archive a completed print from the Jobs page; a note explains the RIP's automatic _archive copy.",
      "Jobs and Runs resolve to the real hot-folder data durably across reinstalls; a loud banner warns when a fallback path is in use.",
      "Print-parameter explainers now pop up instantly as a styled tooltip (no slow native hover bubble).",
    ],
  },
  {
    version: "0.9.0",
    date: "2026-09-17",
    changes: [
      "Live feed panel renamed and de-cluttered; camera selector kept.",
      "Per-stage capture selection (pre-jet / post-jet / post-heat) and a stage filter on Runs stills.",
      "Client-side science-camera capture — the assigned science camera is always the one that shoots.",
      "Removed dry-run mode; a print now guides you to prime the bed before starting.",
      "ChArUco board: custom sizes and a live (non-saved) preview.",
      "Hover tooltips on every print parameter; STOP + reference-at-current share a row; 'go to' no longer clips.",
      "This changelog — click the version in the status bar to see console history.",
    ],
  },
  {
    version: "0.8.6",
    date: "2026-09-16",
    changes: [
      "Lossless WebP capture storage with per-layer CAD-slice alignment.",
      "Per-camera settings (resolution / fps / exposure), including the science camera's high-res modes.",
      "Job vs Print split: Job queues; Print configures and starts.",
      "Timeline-jump no longer reports a false first-layer accuracy error.",
    ],
  },
];

/** The newest changelog version — should equal the baked __APP_VERSION__ (kept in sync by hand). */
export const CHANGELOG_VERSION: string = CHANGELOG[0]?.version ?? "0.0.0";
