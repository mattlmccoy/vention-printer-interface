import { test } from "node:test";
import assert from "node:assert/strict";
import { lensFitText, preflight, residualText, runSweep, selfCheckSummary, waitSettled } from "./autocal.ts";
import type { StatusPayload } from "./telemetry.ts";

function status(o: { state?: string; armed?: boolean; referenced?: Record<string, boolean> | undefined; complete?: boolean } = {}): StatusPayload {
  return {
    controller: {
      state: o.state ?? "connected",
      armed: o.armed ?? true,
      telemetry: { positions: { "4": 463.3 }, referenced: "referenced" in o ? o.referenced : { "4": true }, motion_complete: { "4": o.complete ?? true } },
    },
  } as unknown as StatusPayload;
}
const ready = { capturePoseMm: 463.3, scienceAssigned: true, boardOk: true };

test("preflight is empty when everything is ready", () => {
  assert.deepEqual(preflight({ status: status(), ...ready }), []);
});

test("preflight blocks an unreferenced or unknown-homing recoater", () => {
  assert.match(preflight({ status: status({ referenced: { "4": false } }), ...ready }).join(" "), /home/i);
  assert.match(preflight({ status: status({ referenced: undefined }), ...ready }).join(" "), /home/i);
});

test("preflight lists every missing item", () => {
  const p = preflight({ status: status({ state: "disconnected", armed: false }), capturePoseMm: 0, scienceAssigned: false, boardOk: false });
  const text = p.join(" | ");
  for (const word of [/connected/, /armed/, /capture pose/, /science camera/, /board/]) assert.match(text, word);
  assert.match(preflight({ status: null, ...ready }).join(" "), /operator/);
});

function fakeDeps(usableAt: (mm: number) => boolean, stopAfterMoves = Infinity, startMm = 470, stopOnSample = -1) {
  let samples = 0;
  const calls: string[] = [];
  let moves = 0;
  return {
    calls,
    d: {
      move: async (mm: number) => { moves++; calls.push(`move ${mm}`); },
      settle: async () => { calls.push("settle"); const m = calls.filter((c) => c.startsWith("move")).at(-1); return m ? Number(m.split(" ")[1]) : startMm; },
      capture: async () => { calls.push("capture"); return new Blob(["x"]); },
      readMm: async () => { const m = calls.filter((c) => c.startsWith("move")).at(-1); return m ? Number(m.split(" ")[1]) : startMm; },
      sample: async (_b: Blob, mm: number) => { samples++; calls.push(`sample ${mm}`); return { usable: usableAt(mm) }; },
      stopped: () => moves >= stopAfterMoves || (stopOnSample >= 0 && samples >= stopOnSample),
      stopMotion: async () => { calls.push("stop"); },
    },
  };
}
const plan = { poses: [473.3, 468.3, 463.3, 458.3, 453.3], preApproachMm: 478.3, captureMm: 463.3, windowMinMm: 0, windowMaxMm: 523 };

test("runSweep visits the pre-approach then every pose in order", async () => {
  const { calls, d } = fakeDeps(() => true);
  assert.equal(await runSweep(plan, d), "done");
  assert.deepEqual(calls.filter((c) => c.startsWith("move")), ["move 478.3", "move 473.3", "move 468.3", "move 463.3", "move 458.3", "move 453.3"]);
  assert.deepEqual(calls.filter((c) => c.startsWith("sample")), plan.poses.map((p) => `sample ${p}`));
});

test("runSweep stops before the next move and halts motion", async () => {
  const { calls, d } = fakeDeps(() => true, 3);  // stop once 3 moves have been issued
  assert.equal(await runSweep(plan, d), "stopped");
  assert.equal(calls.filter((c) => c.startsWith("move")).length, 3);
  assert.equal(calls.at(-1), "stop");
});

test("runSweep ends early below the capture pose once the board is lost", async () => {
  const { calls, d } = fakeDeps((mm) => mm > 460);  // 458.3 (below capture) is the first loss
  assert.equal(await runSweep(plan, d), "done");
  assert.ok(!calls.includes("move 453.3"));
  assert.deepEqual(calls.filter((c) => c.startsWith("sample")), ["sample 473.3", "sample 468.3", "sample 463.3", "sample 458.3"]);
});

test("runSweep keeps going above the capture pose when the board is not yet in view", async () => {
  const { calls, d } = fakeDeps((mm) => mm < 470);
  await runSweep(plan, d);
  assert.equal(calls.filter((c) => c.startsWith("sample")).length, 5);
});

// ---- settle (2026-10-21): the first real run photographed MID-MOVE --------------------------------
// MM2 keeps reporting motion_complete=true from the PREVIOUS move for a few polls after a new move is
// issued (backend control/settle.py documents this). The old waitSettled returned on that stale
// "complete": readbacks landed 0.3–3 mm short of each target, the capture-pose photo read 463.6 for
// 463.3 and the solve refused. Settle = the move registered (or a start grace for a no-op move), then
// complete AND the last 3 positions within one 0.1 mm count.
function scripted(samples: Array<[boolean, number]>) {
  let i = 0;
  let t = 0;
  const getStatus = async () => {
    const [complete, pos] = samples[Math.min(i++, samples.length - 1)];
    return { controller: { state: "connected", armed: true, telemetry: { positions: { "4": pos }, referenced: { "4": true }, motion_complete: { "4": complete } } } } as unknown as StatusPayload;
  };
  return { getStatus, opts: { sleep: async (ms: number) => { t += ms; }, now: () => t, pollMs: 50, settleMs: 0 }, reads: () => i };
}

test("waitSettled ignores the stale 'complete' from the previous move", async () => {
  // stale complete at the OLD position, then moving, then at rest on the target
  const s = scripted([[true, 478.3], [true, 478.3], [false, 477.0], [false, 474.1], [true, 473.3], [true, 473.3], [true, 473.3]]);
  assert.equal(await waitSettled(s.getStatus, 4, s.opts), 473.3);
});

test("waitSettled waits for the position to hold, not just 'complete'", async () => {
  const s = scripted([[false, 470], [true, 468.9], [true, 468.5], [true, 468.3], [true, 468.3], [true, 468.3]]);
  assert.equal(await waitSettled(s.getStatus, 4, s.opts), 468.3);
  assert.ok(s.reads() >= 6);
});

test("waitSettled accepts a no-op move after the start grace", async () => {
  const s = scripted([[true, 463.3]]);  // already at target: never goes incomplete
  assert.equal(await waitSettled(s.getStatus, 4, s.opts), 463.3);
});

test("waitSettled times out loudly instead of guessing", async () => {
  const s = scripted([[false, 470]]);
  await assert.rejects(waitSettled(s.getStatus, 4, { ...s.opts, timeoutMs: 2000 }), /did not settle/);
});

test("runSweep refuses a photo when the recoater stopped away from the pose", async () => {
  const { d } = fakeDeps(() => true);
  const off = { ...d, settle: async () => 476.4 };  // never reached 473.3
  await assert.rejects(runSweep(plan, off), /473\.3/);
});

// ---- final-review fixes ---------------------------------------------------------------------
test("runSweep refuses, with no motion, when the recoater starts outside the safety window", async () => {
  const { calls, d } = fakeDeps(() => true, Infinity, 950);  // parked at the far end
  await assert.rejects(runSweep(plan, d), /outside the safety window/);
  assert.equal(calls.filter((c) => c.startsWith("move")).length, 0);
});

test("runSweep refuses, with no motion, when the start position cannot be read", async () => {
  const { calls, d } = fakeDeps(() => true, Infinity, Number.NaN);
  await assert.rejects(runSweep(plan, d), /position/);
  assert.equal(calls.filter((c) => c.startsWith("move")).length, 0);
});

test("Stop pressed during the last photo still ends as stopped (nothing solved)", async () => {
  const { calls, d } = fakeDeps(() => true, Infinity, 470, plan.poses.length);  // stop after the last sample
  assert.equal(await runSweep(plan, d), "stopped");
  assert.equal(calls.at(-1), "stop");
});

test("Stop pressed on the early-exit photo below the capture pose ends as stopped", async () => {
  const { d } = fakeDeps((mm) => mm > 460, Infinity, 470, 4);  // 4th sample (458.3) is the loss
  assert.equal(await runSweep(plan, d), "stopped");
});

test("preflight blocks when the recoater position is not being read", () => {
  const st = status();
  (st.controller.telemetry as unknown as { positions: Record<string, number> }).positions = {};
  assert.match(preflight({ status: st, ...ready }).join(" "), /position/i);
});

test("preflight blocks while a print is running", () => {
  assert.match(preflight({ status: status(), ...ready, printActive: true }).join(" "), /print/i);
});

test("a passing self-check reads ok and states distance error, scale and points used", () => {
  const s = selfCheckSummary({ rms_mm: 0.012, worst_mm: 0.031, scale_bias: 1.0004, n_used: 38, n_outside: 3, moved: true, passed: true, reasons: [] });
  assert.equal(s.tone, "ok");
  assert.match(s.headline, /passed/);
  assert.match(s.detail, /0\.012 mm RMS/);
  assert.match(s.detail, /38 points used, 3 outside/);
});

test("a self-check on an unmoved board warns even when it passed", () => {
  const s = selfCheckSummary({ rms_mm: 0.01, worst_mm: 0.02, scale_bias: 1, n_used: 41, n_outside: 0, moved: false, passed: true, reasons: ["the board did not move since the sweep"] });
  assert.equal(s.tone, "warn");
  assert.match(s.headline, /did not move/);
});

test("a self-check with no point pairs never shows a number as if it were measured", () => {
  const s = selfCheckSummary({ rms_mm: null, worst_mm: null, scale_bias: null, n_used: 0, n_outside: 0, moved: true, passed: false, reasons: ["only 0 board points inside the calibrated area (need 12)"] });
  assert.equal(s.tone, "err");
  assert.doesNotMatch(s.detail, /0\.000/);
  assert.match(s.detail, /no distances measured/);
});

test("the lens fit is shown in mm on the bed, with the pixels and the mm limit", () => {
  assert.equal(lensFitText({ reprojection_rms_px: 1.4, reprojection_rms_mm: 0.0361, px_mm: 0.0258, reprojection_limit_mm: 0.05 }),
    "0.036 mm RMS on the bed (1.40 px at 0.0258 mm/px) — limit 0.05 mm");
});

test("an older operator without the mm figure falls back to pixels, labelled as such", () => {
  assert.equal(lensFitText({ reprojection_rms_px: 0.285 }), "0.285 px RMS (older operator: no mm figure)");
});

test("the residual breakdown names where the misfit is, skipping empty groups", () => {
  const t = residualText({
    corner: { n: 200, rms_px: 0.8 }, marker: { n: 700, rms_px: 1.5 },
    centre: { n: 300, rms_px: 0.6 }, middle: { n: 400, rms_px: 1.1 }, edge: { n: 0, rms_px: null },
  });
  assert.equal(t, "corners 0.80 px (200) · markers 1.50 px (700) · centre 0.60 px (300) · middle 1.10 px (400)");
});

// ---- settle (2026-10-21, second real run): cached telemetry counted as "stable" ------------------
// The console polls /api/status every 50 ms but the operator re-reads the MM2 position only every
// ~290 ms, and once MM2 answers "complete" (stale, from the previous move) the operator stops
// asking. Three polls of ONE cached sample looked "stable" 0.5 s into a 5 mm move; the pose check
// then refused the photo and the run stopped (at 403.3 mm, and on the first pose of earlier runs).
// Real log: move 15:39:52.130, complete/W read at .312 and .559 only, browser gave up ~.6.
function cached(samples: Array<[boolean, number]>, pollsPerSample = 6) {
  let i = 0;
  let t = 0;
  const getStatus = async () => {
    const n = Math.floor(i++ / pollsPerSample);  // the operator keeps sampling: new timestamps forever
    const [complete, pos] = samples[Math.min(n, samples.length - 1)];
    return { controller: { state: "connected", armed: true, telemetry: { host_timestamp_ns: 1_000_000 * (n + 1), positions: { "4": pos }, referenced: { "4": true }, motion_complete: { "4": complete } } } } as unknown as StatusPayload;
  };
  return { getStatus, opts: { sleep: async (ms: number) => { t += ms; }, now: () => t, pollMs: 50, settleMs: 0 }, elapsed: () => t };
}

test("waitSettled counts only fresh telemetry samples, never one cached sample polled 3 times", async () => {
  // stale 'complete' the whole way (the operator stopped asking); one sample per 6 polls
  const s = cached([[true, 408.3], [true, 407.0], [true, 404.9], [true, 403.3], [true, 403.3], [true, 403.3]]);
  assert.equal(await waitSettled(s.getStatus, 4, s.opts), 403.3);
});

test("waitSettled does not accept a still position away from the target until it has held a while", async () => {
  // the move registers late: three fresh samples still at the old position, then it moves
  const s = cached([[true, 408.3], [true, 408.3], [true, 408.3], [true, 408.3], [true, 406.0], [true, 403.3], [true, 403.3], [true, 403.3]]);
  assert.equal(await waitSettled(s.getStatus, 4, { ...s.opts, targetMm: 403.3 }), 403.3);
});

test("waitSettled still reports an axis that really stopped short (after the hold), for the pose check", async () => {
  const s = cached([[true, 408.3], [true, 405.0]]);
  assert.equal(await waitSettled(s.getStatus, 4, { ...s.opts, targetMm: 403.3, farHoldMs: 2000 }), 405.0);
  assert.ok(s.elapsed() >= 2000);
});
