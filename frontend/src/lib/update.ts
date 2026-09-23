/** Operator update detection: is the local operator behind the version this site was built from,
 *  and what command re-installs (which updates + restarts) it on each OS. */

export type Os = "mac" | "windows" | "linux" | "other";

const REPO = "https://raw.githubusercontent.com/mattlmccoy/vention-printer-interface/main";

/** Parse "0.2.0" → [0,2,0]; null when it isn't a dotted numeric version (e.g. "dev", ""). */
function parse(v: string | null | undefined): number[] | null {
  if (!v) return null;
  const parts = v.trim().split(".");
  if (parts.length === 0) return null;
  const nums = parts.map((p) => Number(p));
  return nums.every((n) => Number.isInteger(n) && n >= 0) ? nums : null;
}

function cmp(a: number[], b: number[]): number {
  const n = Math.max(a.length, b.length);
  for (let i = 0; i < n; i++) {
    const d = (a[i] ?? 0) - (b[i] ?? 0);
    if (d !== 0) return d < 0 ? -1 : 1;
  }
  return 0;
}

/** True only when both versions parse and the operator's is strictly older than the site's.
 *  Unknown/unparseable/operator-ahead all return false — never nag on uncertainty. */
export function operatorBehind(operatorVersion: string | null | undefined, siteVersion: string): boolean {
  const op = parse(operatorVersion);
  const site = parse(siteVersion);
  if (op === null || site === null) return false;
  return cmp(op, site) < 0;
}

export function detectOs(userAgent: string): Os {
  const ua = userAgent.toLowerCase();
  if (ua.includes("mac")) return "mac";
  if (ua.includes("win")) return "windows";
  if (ua.includes("linux") || ua.includes("x11")) return "linux";
  return "other";
}

/** The install one-liner for an OS — re-running it updates the checkout, rebuilds, and restarts the
 *  always-on operator service (idempotent; see install.sh / install.ps1). */
export function updateCommand(os: Os): { label: string; command: string } {
  if (os === "windows") {
    return { label: "Windows (PowerShell)", command: `irm ${REPO}/install.ps1 | iex` };
  }
  const label = os === "mac" ? "macOS" : os === "linux" ? "Linux" : "macOS / Linux";
  return { label, command: `curl -fsSL ${REPO}/install.sh | bash` };
}

/** The OPERATOR's OS, from /api/health `platform` (Python platform.platform(), e.g.
 *  "macOS-27.0-arm64-arm-64bit-Mach-O"). Preferred over the browser's user agent: the console may
 *  be open on a different machine than the operator. Null when unrecognised. */
export function osFromPlatform(platform: string | null): Os | null {
  const p = (platform ?? "").toLowerCase();
  if (p.startsWith("macos") || p.startsWith("darwin")) return "mac";
  if (p.startsWith("windows")) return "windows";
  if (p.startsWith("linux")) return "linux";
  return null;
}

const TASK = "Binder Jet Console operator"; // deploy/install-operator-service.ps1

/** Update an ALREADY-installed operator in place: back onto main (another session may have left a
 *  PR branch checked out), pull, sync keeping the plots extra, restart the service. Deliberately NOT
 *  the install one-liner: re-installing regenerates the macOS LaunchAgent plist and drops flags added
 *  to it (e.g. --print-min-wait). Assumes the default checkout ~/vention-printer-interface. */
export function inPlaceUpdateCommand(os: Os): { label: string; command: string } {
  const sync = "uv sync --inexact --extra plots";
  if (os === "windows") {
    return {
      label: "Windows (PowerShell)",
      command: `cd $HOME\\vention-printer-interface; git checkout main; git pull --ff-only; cd backend; ${sync}; cd ..; Stop-ScheduledTask -TaskName "${TASK}"; Start-ScheduledTask -TaskName "${TASK}"`,
    };
  }
  const restart = os === "linux"
    ? "systemctl --user restart vpi-operator.service"
    : "launchctl kickstart -k gui/$(id -u)/com.binderjet.operator";
  return {
    label: os === "linux" ? "Linux" : "macOS",
    command: `cd ~/vention-printer-interface && git checkout main && git pull --ff-only && (cd backend && ${sync}) && ${restart}`,
  };
}

/** What a console ≠ operator mismatch means and what to do. Versions decide the direction; the
 *  same version on different commits can't be ordered here, so reload first, then update. */
export function mismatchAdvice(i: { siteVersion: string; opVersion: string | null }): {
  behind: "operator" | "console" | "unknown"; showCommand: boolean; text: string;
} {
  const op = parse(i.opVersion);
  const site = parse(i.siteVersion);
  const reload = "Reload this page (Cmd/Ctrl+Shift+R) — the browser may be showing a cached console.";
  if (op && site && cmp(op, site) < 0) {
    return { behind: "operator", showCommand: true, text: `The operator (v${i.opVersion}) is older than this console (v${i.siteVersion}). Run this on the operator machine; it restarts itself — then reconnect.` };
  }
  if (op && site && cmp(op, site) > 0) {
    return { behind: "console", showCommand: false, text: `This console (v${i.siteVersion}) is older than the operator (v${i.opVersion}). ${reload} A new release can take a minute or two to reach GitHub Pages.` };
  }
  return { behind: "unknown", showCommand: true, text: `Same version, different commits. ${reload} If it still differs, update the operator:` };
}
