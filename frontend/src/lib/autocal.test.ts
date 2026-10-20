import { test } from "node:test";
import assert from "node:assert/strict";
import { preflight, runSweep, waitSettled } from "./autocal.ts";
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

function fakeDeps(usableAt: (mm: number) => boolean, stopAfterMoves = Infinity) {
  const calls: string[] = [];
  let moves = 0;
  return {
    calls,
    d: {
      move: async (mm: number) => { moves++; calls.push(`move ${mm}`); },
      settle: async () => { calls.push("settle"); },
      capture: async () => { calls.push("capture"); return new Blob(["x"]); },
      readMm: async () => Number(calls.filter((c) => c.startsWith("move")).at(-1)!.split(" ")[1]),
      sample: async (_b: Blob, mm: number) => { calls.push(`sample ${mm}`); return { usable: usableAt(mm) }; },
      stopped: () => moves >= stopAfterMoves,
      stopMotion: async () => { calls.push("stop"); },
    },
  };
}
const plan = { poses: [473.3, 468.3, 463.3, 458.3, 453.3], preApproachMm: 478.3, captureMm: 463.3 };

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

test("waitSettled waits for motion_complete then settles", async () => {
  const seq = [false, false, true];
  const slept: number[] = [];
  let i = 0;
  await waitSettled(async () => status({ complete: seq[Math.min(i++, 2)] }), 4, { sleep: async (ms) => { slept.push(ms); }, settleMs: 400 });
  assert.equal(i, 3);
  assert.equal(slept.at(-1), 400);
});
