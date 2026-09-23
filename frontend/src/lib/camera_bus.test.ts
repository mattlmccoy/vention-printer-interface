import { test } from "node:test";
import assert from "node:assert/strict";
import { captureFullResStill, createCameraBus } from "./camera_bus.ts";

test("pausing reaches every live view once; resume reaches them after the last pause ends", () => {
  const bus = createCameraBus();
  const log: string[] = [];
  const off = bus.subscribe({ pause: () => log.push("a:pause"), resume: () => log.push("a:resume") });
  bus.subscribe({ pause: () => log.push("b:pause"), resume: () => log.push("b:resume") });
  bus.pause();
  bus.pause(); // nested: no second pause event
  bus.resume();
  assert.deepEqual(log, ["a:pause", "b:pause"]); // still paused (one holder left)
  bus.resume();
  assert.deepEqual(log, ["a:pause", "b:pause", "a:resume", "b:resume"]);
  off();
  bus.pause();
  assert.deepEqual(log.slice(4), ["b:pause"]);
  assert.equal(bus.paused(), true);
});

const fakeStream = (log: string[]) => ({ getTracks: () => [{ stop: () => log.push("stop") }] }) as unknown as MediaStream;

test("full-res capture: pause live views -> release -> open alone -> grab -> close -> resume", async () => {
  const bus = createCameraBus();
  const log: string[] = [];
  bus.subscribe({ pause: () => log.push("pause"), resume: () => log.push("resume") });
  let t = 0;
  const r = await captureFullResStill({
    bus,
    releaseMs: 250,
    sleep: async (ms) => { log.push(`sleep ${ms}`); t += ms; },
    now: () => t,
    open: async () => { log.push("open"); t += 900; return fakeStream(log); },
    grab: async () => { log.push("grab"); t += 150; return { blob: new Blob(["x"]), attempts: [] }; },
  });
  assert.deepEqual(log, ["pause", "sleep 250", "open", "grab", "stop", "resume"]);
  assert.ok(r.blob);
  assert.equal(r.openMs, 900);
  assert.equal(r.totalMs, 1300);
});

test("live views resume even when the full-res open fails, and the reason is kept", async () => {
  const bus = createCameraBus();
  const log: string[] = [];
  bus.subscribe({ pause: () => log.push("pause"), resume: () => log.push("resume") });
  const r = await captureFullResStill({
    bus, releaseMs: 0, sleep: async () => {}, now: () => 0,
    open: async () => { throw new Error("NotReadableError: Could not start video source"); },
    grab: async () => ({ blob: null, attempts: [] }),
  });
  assert.equal(r.blob, null);
  assert.match(r.attempts.join(";"), /open full-res: .*Could not start video source/);
  assert.deepEqual(log, ["pause", "resume"]);
  assert.equal(bus.paused(), false);
});
