/** The Priming tab's own guided walkthrough model: six operator-facing steps for loading powder
 *  into the machine and levelling the bed. This is deliberately NOT the compiled priming macro's
 *  step list — the operator sees these plain-language steps, never the macro's raw step count
 *  (status.print.n_steps / step_index), which confused them. */
export interface WalkStep {
  id: "amount" | "build-up" | "open-feed" | "load" | "level" | "finish";
  title: string;
}

export const WALKTHROUGH_STEPS: readonly WalkStep[] = [
  { id: "amount", title: "Amount" },
  { id: "build-up", title: "Build piston up" },
  { id: "open-feed", title: "Open feed cavity" },
  { id: "load", title: "Load powder" },
  { id: "level", title: "Thick precoats" },
  { id: "finish", title: "Finish" },
];

const clampStep = (i: number): number => Math.min(Math.max(i, 0), WALKTHROUGH_STEPS.length - 1);

/** "Step 3 of 6 — Open feed cavity" for the walkthrough's own 1-based position. Out-of-range
 *  indices clamp into the valid range so the heading is always a real step. */
export function stepHeading(index: number): string {
  const i = clampStep(index);
  return `Step ${i + 1} of ${WALKTHROUGH_STEPS.length} — ${WALKTHROUGH_STEPS[i].title}`;
}
