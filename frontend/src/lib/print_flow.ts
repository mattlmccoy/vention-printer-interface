// Configure → Prime → Start: where a print stands before START, from the saved plan and the
// operator's primed-bed status (GET /api/primed → status; control/primed_state.py).

export type PrimeState = "none" | "ready" | "other_plan" | "used" | "unverified";
export interface PrimeStatus { state: PrimeState; reason: string }
export interface FlowStep { id: "configure" | "prime" | "start"; label: string; state: "done" | "current" | "todo"; note: string }
export interface PrintFlow {
  steps: FlowStep[];
  /** go = START as usual · override = START only with an explicit "start anyway" (sends
   *  accept_prime_risk) · blocked = START disabled */
  startMode: "go" | "override" | "blocked";
  startNote: string;
}

/** The three-step strip for the Print tab. Only a bed the operator reports as primed for THIS
 *  plan counts as done; an operator that reports no status is unknown, never ready. */
export function printFlow(i: { planValid: boolean; dirty: boolean; prime: PrimeStatus | null }): PrintFlow {
  const configured = i.planValid && !i.dirty;
  const configure: FlowStep = {
    id: "configure", label: "Configure",
    state: configured ? "done" : "current",
    note: !i.planValid ? "fix the settings below" : i.dirty ? "unsaved changes" : "settings saved",
  };
  const primeState = i.prime?.state ?? null;
  const primeReady = primeState === "ready";
  const pending = i.dirty ? " · re-checked after you save" : "";
  const prime: FlowStep = {
    id: "prime", label: "Prime",
    state: primeReady ? "done" : "current",
    note: (i.prime?.reason ?? "the operator didn't report the primed-bed status") + pending,
  };
  const start: FlowStep = {
    id: "start", label: "Start",
    state: configured && primeReady ? "current" : "todo",
    note: "",
  };
  let startMode: PrintFlow["startMode"] = "go";
  let startNote = "";
  if (!i.planValid) { startMode = "blocked"; startNote = "fix the print settings first"; }
  else if (primeState === "none") { startMode = "blocked"; startNote = "prime the bed first"; }
  else if (!primeReady) { startMode = "override"; startNote = prime.note; }
  start.note = startNote;
  return { steps: [configure, prime, start], startMode, startNote };
}
