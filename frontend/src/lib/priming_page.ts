// The priming page's model: which motor moves each walkthrough step issues, the powder budget bar,
// and the single status line. Kept pure so the physical moves (axis, direction, target) are tested.

import { fmtMmAuto } from "./format.ts";

/** One numbered move in a step's row. `value` is null when its target isn't loaded (unrunnable).
 *  Axes: 1 build piston, 2 feed piston, 4 recoater (positions are mm below flush for pistons). */
export interface StepMove { n: number; label: string; axis: number; mode: "abs" | "rel"; value: number | null; key: string }

const get = (s: Record<string, number> | null, k: string): number | null =>
  s && typeof s[k] === "number" ? s[k] : null;

/** The moves a walkthrough step runs, in order. Mirrors compile_priming_setup
 *  (control/priming.py): a thick precoat is recoater to start (past the feed) → feed UP by the
 *  feed amount (a NEGATIVE relative move: position is depth below flush) → spread across. The
 *  build piston never moves during precoats. `feedOverride` is the operator's per-coat amount. */
export function stepMoves(id: string, s: Record<string, number> | null, feedOverride: number | null): StepMove[] {
  if (id === "build-up") {
    return [{ n: 1, label: "Build piston to the top", axis: 1, mode: "abs", value: get(s, "part_top_mm"), key: "part_top_mm" }];
  }
  if (id === "open-feed") {
    return [{ n: 1, label: "Feed piston down to open the cavity", axis: 2, mode: "abs", value: get(s, "feed_cavity_mm"), key: "feed_cavity_mm" }];
  }
  if (id === "level") {
    const feed = feedOverride != null && feedOverride > 0 ? feedOverride : get(s, "thick_feed_mm");
    return [
      { n: 1, label: "Recoater to start (past the feed)", axis: 4, mode: "abs", value: get(s, "level_recoat_start_mm"), key: "level_recoat_start_mm" },
      { n: 2, label: "Feed up — supply powder", axis: 2, mode: "rel", value: feed == null ? null : -feed, key: "thick_feed_mm" },
      { n: 3, label: "Spread across the bed", axis: 4, mode: "abs", value: get(s, "level_recoat_end_mm"), key: "level_recoat_end_mm" },
    ];
  }
  return [];
}

export interface PrimingBudget { needMm: number | null; haveMm: number | null; tone: "ok" | "warn" | "bad"; text: string }

/** Needed vs in-the-feed powder, for the bar pinned on every step. Before the thick precoats the
 *  feed must also supply them (+ margin); after them only the print's own feed is left to supply.
 *  "In the feed" is the live feed depth, trusted only when the axis is homed. Like the print's
 *  run-out guard, enough means STRICTLY more than needed. */
export function primingBudget(i: {
  feedDemandMm: number | null; thickFeedMm: number; marginMm: number;
  feedPosMm: number | null; feedReferenced: boolean; afterPrecoats: boolean;
}): PrimingBudget {
  const needMm = i.feedDemandMm == null ? null
    : i.afterPrecoats ? i.feedDemandMm : i.feedDemandMm + i.thickFeedMm + i.marginMm;
  const haveMm = i.feedReferenced && i.feedPosMm != null ? i.feedPosMm : null;
  const what = i.afterPrecoats ? "the print needs" : "print + thick precoats + margin need";
  if (needMm == null) return { needMm, haveMm, tone: "warn", text: "the print's feed demand isn't loaded yet" };
  const need = `${what} ${fmtMmAuto(needMm, 1)}`;
  if (haveMm == null) {
    return { needMm, haveMm, tone: "warn", text: `${need} · can't verify the feed: it hasn't been homed since power-on` };
  }
  const have = `${fmtMmAuto(haveMm, 1)} in the feed`;
  return haveMm > needMm
    ? { needMm, haveMm, tone: "ok", text: `${need} · ${have}` }
    : { needMm, haveMm, tone: "bad", text: `${need} · only ${have} — open the cavity deeper` };
}

export interface StatusLine { tone: "ok" | "warn" | "idle"; text: string; actions: ("resume" | "abort" | "capture")[] }

/** One fixed line for the machine/macro state (replaces the banners that came and went). */
export function primingStatusLine(
  p: { state: string; macro: string | null; reason: string; step_index: number; n_steps: number } | null,
  connected: boolean,
): StatusLine {
  if (!connected || !p) return { tone: "idle", text: "not connected — connect to run priming moves", actions: [] };
  const active = p.state === "running" || p.state === "paused";
  if (p.macro === "priming") {
    if (p.state === "paused") {
      return { tone: "warn", text: `priming paused · ${p.reason || "load powder into the feed cavity, then Resume"}`, actions: ["resume", "abort"] };
    }
    if (p.state === "running") {
      const pct = p.n_steps ? Math.round((100 * p.step_index) / p.n_steps) : 0;
      return { tone: "ok", text: `priming running · ${pct}%`, actions: ["abort"] };
    }
    if (p.state === "done") return { tone: "ok", text: "priming complete · capture the primed bed", actions: ["capture"] };
  }
  if (active) return { tone: "warn", text: `a ${p.macro ?? "print"} is running — priming moves are locked`, actions: ["abort"] };
  return { tone: "idle", text: "ready · run each step, or RUN PRIMING below for the automatic routine", actions: [] };
}
