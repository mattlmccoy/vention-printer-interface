import type { FeedBudgetPayload } from "./api.ts";
import { fmtMmAuto } from "./format.ts";

export type BudgetTone = "ok" | "warn" | "bad";
export interface BudgetLine { tone: BudgetTone; text: string }

/** One status line for the feed-powder budget before START. Unknown (not homed, no telemetry, not
 *  loaded yet) is a warning — it must never read as "enough powder". */
export function feedBudgetLine(b: FeedBudgetPayload | null): BudgetLine {
  if (!b) return { tone: "warn", text: "Powder budget unknown — the operator hasn't reported it" };
  const need = `${fmtMmAuto(b.demand_mm, 1)} needed`;
  if (b.available_mm === null || b.sufficient === null) {
    return { tone: "warn", text: `${need} · can't verify the feed: ${b.unknown_reason ?? "position unknown"}` };
  }
  const have = `${fmtMmAuto(b.available_mm, 1)} in the feed`;
  if (b.sufficient) return { tone: "ok", text: `${need} · ${have}` };
  return { tone: "bad", text: `${need} · ${have} — stops after layer ${b.layers_supported} of ${b.layers_total}` };
}

/** True when POST /api/print/start refused because of the powder budget (so START can offer
 *  "start anyway" with accept_feed_risk). Matches the backend's _check_feed_budget details. */
export function isFeedBudgetRefusal(e: unknown): boolean {
  const msg = e instanceof Error ? e.message : "";
  return /^409 (Not enough powder in the feed|Can't check the powder in the feed)/.test(msg);
}
