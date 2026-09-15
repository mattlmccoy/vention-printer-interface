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
