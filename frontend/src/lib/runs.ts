// Run outcome → chip presentation. The status string is derived server-side (recorder
// derive_run_status, verified against real events.json); this only maps it to a label + a theme
// token. An unknown/absent status degrades to a neutral placeholder so it never reads as success.

export interface RunChip {
  key: string;
  label: string;
  color: string; // a theme.css token, e.g. "var(--live)"
  title: string; // hover explanation
}

const CHIPS: Record<string, RunChip> = {
  finished: { key: "finished", label: "finished", color: "var(--live)", title: "print completed (print_done)" },
  aborted: { key: "aborted", label: "aborted", color: "var(--warn)", title: "print aborted by the operator" },
  fault: { key: "fault", label: "fault", color: "var(--err)", title: "ended in a fault or e-stop" },
  running: { key: "running", label: "running", color: "var(--accent)", title: "currently recording" },
  incomplete: { key: "incomplete", label: "incomplete", color: "var(--muted)", title: "a print began but recorded no terminal outcome" },
  recorded: { key: "recorded", label: "recorded", color: "var(--muted)", title: "telemetry-only session (no print)" },
};

const UNKNOWN: RunChip = { key: "unknown", label: "run", color: "var(--faint)", title: "outcome unknown" };

/** Map a run's derived status string to its chip label + theme token. Unknown/absent → neutral. */
export function runStatusChip(status: string | undefined | null): RunChip {
  return (status && CHIPS[status]) || UNKNOWN;
}

/** Badge text for where a run's data lives, or null to show nothing (local-only is the default and
 *  needs no badge). Drive-resident (offloaded, freed locally) reads "on <drive>"; present in both
 *  reads "local + <drive>". Mirrors the backend `locations` union (recording/libraries.merge_runs). */
export function runLocationLabel(locations: string[] | undefined): string | null {
  const locs = locations ?? [];
  const drives = locs.filter((l) => l !== "local");
  if (drives.length === 0) return null; // local-only (or unknown) — no badge
  if (locs.includes("local")) return `local + ${drives.join(" + ")}`;
  return `on ${drives.join(" + ")}`;
}
