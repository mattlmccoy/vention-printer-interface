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
    version: "0.12.1",
    date: "2026-09-23",
    changes: [
      "Truncated camera frames (the bottom never arrived over USB — a green band) are refused instead of being saved as science captures; the browser tries its next grab.",
      "Capture failures now say why: each browser attempt's reason and the operator fallback's answer, not only a 503.",
      "Camera fps limits follow the camera's real modes, with a warning when an uncompressed mode needs more USB bandwidth than a shared hub carries.",
      "Timeline, step and event-log numbers no longer show floating-point noise.",
      "Clicking the console ≠ operator badge explains the mismatch and gives the update command for the operator's OS.",
    ],
  },
  {
    version: "0.12.0",
    date: "2026-09-23",
    changes: [
      "Camera controls on the Mac: the operator reads and sets the camera's own controls (exposure, gain, brightness, white balance, focus and more) with their real ranges and factory defaults — the Mac browser exposes none of them.",
      "Reset camera settings to default: clears saved capture settings and sliders, returns browser controls to auto and, on the Mac, restores the camera's factory settings.",
      "Configure → Prime → Start: a primed bed belongs to the plan it was primed for and is used up by a print; START is blocked until primed and asks before printing on a bed primed for a different plan.",
      "Priming page redesign: numbered move rows with inline targets on every step, a pinned powder bar and status line, pinned Back/Next.",
      "Fixed: a priming move run right after typing a new target could use the old target.",
    ],
  },
  {
    version: "0.11.1",
    date: "2026-09-23",
    changes: [
      "Powder budget: START checks the powder in the feed against what the print needs. A short feed is refused with where it would stop; an unhomed feed needs confirmation; starting anyway stops safely when the powder runs out. The Print tab shows a live powder line.",
      "Priming: the 'paired to job' fill depth now counts the print's feed (not the build thickness) plus the thick precoats' feed — the old amount under-filled by about half.",
    ],
  },
  {
    version: "0.11.0",
    date: "2026-09-23",
    changes: [
      "Data offload: copy or MOVE runs to an external drive with hash verification (read-only disk images are hidden). Runs stay visible and viewable in Runs whether they live on this computer or a drive, can be restored back to local, and Reveal on disk works for drive runs.",
      "Storage: science stills are no longer saved twice when the camera is uncalibrated (~36% smaller runs; existing runs can be cleaned with the dedup tool), and overview timelapse frames are lighter.",
      "Printing: opt-in absolute layer seat stops build-height error from accumulating; the timeline follows the running step with a clear 'now' readout; shorter default dwells and tunable print pacing.",
      "Pistons: in-app backlash calibration with live plots, a re-measure check, a stable recommendation and saved history; per-cylinder max travel and a guard against builds beyond usable travel.",
      "Cameras & calibration: coverage-gated science-camera calibration with independent scale validation, calibration through the browser camera, an automatic camera-center sweep for the capture pose, and ignoring unwanted cameras.",
      "Windows: a 'Grant camera access' button, the real reason when a camera can't open, and camera names on Windows.",
      "Cameras: ignored cameras (like the built-in FaceTime camera) are hidden everywhere; the Settings tab is now 'Camera inventory'. ChArUco: large custom boards no longer overload the operator, and a preset board carries its parameters straight into calibration with the mm/px and bed-extent fields explained.",
      "Interface: alerts float over the page instead of pushing it down, archived jobs get their own section, a 5 mm jog step, numbers without floating-point noise, and the status bar shows the operator's exact commit so updates are visible.",
      "Analysis: exportable publication-style plots for backlash, layer accuracy, validation and sweeps.",
    ],
  },
  {
    version: "0.10.4",
    date: "2026-09-20",
    changes: [
      "ChArUco calibration board now includes a red CUT-layer outline so the laser cuts the board free from the stock (toggle it off for pre-cut pieces); every shipped preset is verified detectable by the OpenCV ChArUco detector.",
    ],
  },
  {
    version: "0.10.3",
    date: "2026-09-18",
    changes: [
      "Pre-jet, post-jet, and post-heat science stills now stop at the commissioned camera pose, settle, and hold until the browser finishes the exposure.",
      "Overview timelapse playback now assembles bounded previews instead of retaining every 4K frame in memory; original captured frames remain untouched.",
      "The overview timelapse switch and interval now live with the other run settings on the Print page.",
    ],
  },
  {
    version: "0.10.2",
    date: "2026-09-18",
    changes: [
      "Science captures now stay bound to the exact USB camera selected in the browser; unsafe macOS index fallback can no longer wake an iPhone Continuity Camera.",
      "Blank and near-uniform camera frames are rejected instead of being saved as successful layer captures.",
      "Camera permission checks no longer open an unspecified camera, and capture streams use bandwidth-safe previews before requesting a full-resolution still.",
    ],
  },
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
