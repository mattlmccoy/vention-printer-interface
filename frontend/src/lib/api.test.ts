import { test } from "node:test";
import assert from "node:assert/strict";

// Provide the browser globals api.ts touches at import time.
(globalThis as unknown as { localStorage: null }).localStorage = null;
const { api, CLIENT_HEADER } = await import("./api.ts");

interface Call { method: string; url: string; body: unknown; headers: Record<string, string> }
const calls: Call[] = [];
(globalThis as unknown as { fetch: typeof fetch }).fetch = (async (url: string, init?: RequestInit) => {
  calls.push({ method: init?.method ?? "GET", url, body: init?.body ? JSON.parse(String(init.body)) : undefined, headers: (init?.headers ?? {}) as Record<string, string> });
  return new Response(JSON.stringify({ ok: true, detail: "x" }), { status: 200, headers: { "Content-Type": "application/json" } });
}) as typeof fetch;

async function last(fn: () => Promise<unknown>): Promise<Call> { await fn(); return calls[calls.length - 1]; }

test("every route: method + path + body locked", async () => {
  const cases: Array<[() => Promise<unknown>, string, string, unknown]> = [
    [() => api.health(), "GET", "/api/health", undefined],
    [() => api.status(), "GET", "/api/status", undefined],
    [() => api.discovery(), "GET", "/api/discovery", undefined],
    [() => api.connect({ backend: "simulated" }), "POST", "/api/connect", { backend: "simulated" }],
    [() => api.disconnect(), "POST", "/api/disconnect", undefined],
    [() => api.arm(), "POST", "/api/arm", undefined],
    [() => api.disarm(), "POST", "/api/disarm", undefined],
    [() => api.estop(), "POST", "/api/estop", undefined],
    [() => api.estopRelease(), "POST", "/api/estop/release", undefined],
    [() => api.estopResetDrives(), "POST", "/api/estop/reset-drives", undefined],
    [() => api.clearFault(), "POST", "/api/clear-fault", undefined],
    [() => api.home([3]), "POST", "/api/motion/home", { axes: [3] }],
    [() => api.move(3, "rel", -10), "POST", "/api/motion/move", { axis: 3, mode: "rel", mm: -10 }],
    [() => api.stop(), "POST", "/api/motion/stop", {}],
    [() => api.axisMotion(2), "GET", "/api/axes/2/motion", undefined],
    [() => api.setAxisMotion(2, { max_speed: 5 }), "PUT", "/api/axes/2/motion", { max_speed: 5 }],
    [() => api.limits(), "GET", "/api/safety-limits", undefined],
    [() => api.setLimits({ heater_max_on_s: 30 }), "PUT", "/api/safety-limits", { heater_max_on_s: 30 }],
    [() => api.heaterOn(), "POST", "/api/heater/on", undefined],
    [() => api.heaterOff(), "POST", "/api/heater/off", undefined],
    [() => api.printSettings(), "GET", "/api/print-settings", undefined],
    [() => api.setPrintSettings({ heater_enabled: true }), "PUT", "/api/print-settings", { heater_enabled: true }],
    [() => api.printStart({ single_step: false }), "POST", "/api/print/start", { single_step: false }],
    [() => api.printPause(), "POST", "/api/print/pause", undefined],
    [() => api.printResume(), "POST", "/api/print/resume", undefined],
    [() => api.printStep(), "POST", "/api/print/step", undefined],
    [() => api.printAbort(), "POST", "/api/print/abort", undefined],
    [() => api.setSingleStep(true), "POST", "/api/print/single-step", { on: true }],
    [() => api.printSteps(), "GET", "/api/print/steps", undefined],
    [() => api.printSeek(4), "POST", "/api/print/seek", { index: 4 }],
    [() => api.recordingStart({ name: "a", notes: "" }), "POST", "/api/recording/start", { name: "a", notes: "" }],
    [() => api.recordingStop(), "POST", "/api/recording/stop", undefined],
    [() => api.recordings(), "GET", "/api/recordings", undefined],
    [() => api.jobs(), "GET", "/api/jobs", undefined],
    [() => api.selectJob("/x/y"), "POST", "/api/jobs/select", { path: "/x/y" }],
    [() => api.clearJob(), "POST", "/api/jobs/clear", undefined],
    [() => api.macro("load_cart"), "POST", "/api/macro/load_cart", undefined],
    [() => api.priming(), "GET", "/api/priming", undefined],
    [() => api.setPriming({ feed_start_mm: 30 }), "PUT", "/api/priming", { feed_start_mm: 30 }],
    [() => api.primingRun(), "POST", "/api/priming/run", undefined],
    [() => api.primed(), "GET", "/api/primed", undefined],
    [() => api.primedCapture(), "POST", "/api/primed/capture", undefined],
    [() => api.scienceClientFallback(17), "POST", "/api/vision/science/client-fallback?seq=17", undefined],
    [() => api.events(), "GET", "/api/events", undefined],
    [() => api.autoLog(), "GET", "/api/auto-log", undefined],
    [() => api.setAutoLog(false), "PUT", "/api/auto-log", { enabled: false }],
    [() => api.setIgnoredCameras(["0xAAA"]), "PUT", "/api/vision/ignored-cameras", { unique_ids: ["0xAAA"] }],
    [() => api.backlashHistory(), "GET", "/api/motion/backlash/history", undefined],
    [() => api.backlashRecord("backlash_a1_x"), "GET", "/api/motion/backlash/history/backlash_a1_x", undefined],
    [() => api.offloadDrives(), "GET", "/api/offload/drives", undefined],
    [() => api.offloadPlan("/Volumes/X"), "GET", "/api/offload/plan?dest=%2FVolumes%2FX", undefined],
    [() => api.offloadStart("/Volumes/X"), "POST", "/api/offload/start", { dest: "/Volumes/X", runs: null }],
    [() => api.offloadJob(), "GET", "/api/offload/job", undefined],
    [() => api.offloadCancel(), "POST", "/api/offload/cancel", undefined],
    [() => api.timing(), "GET", "/api/config/timing", undefined],
    [() => api.setTiming({ print_min_wait_s: 0.1 }), "PUT", "/api/config/timing", { print_min_wait_s: 0.1 }],
    [() => api.plotBacklash("png"), "GET", "/api/plots/backlash.png", undefined],
    [() => api.plotLayerAccuracy("20260101_000000_run", "pdf"),
      "GET", "/api/plots/layer-accuracy/20260101_000000_run.pdf", undefined],
    [() => api.plotValidation([0.01, 0.03], 0.05, "png"),
      "POST", "/api/plots/validation.png", { residuals_mm: [0.01, 0.03], target_mm: 0.05 }],
    [() => api.plotSweep([{ commanded_mm: 10, deviation_mm: 0, direction: "down" }], "png"),
      "POST", "/api/plots/sweep.png", { rows: [{ commanded_mm: 10, deviation_mm: 0, direction: "down" }] }],
    [() => api.centerSweepStart({ span_mm: 4, step_mm: 1 }), "POST", "/api/vision/center-sweep/session", { span_mm: 4, step_mm: 1 }],
    [() => api.centerSweepStatus(), "GET", "/api/vision/center-sweep/session", undefined],
    [() => api.centerSweepBest(), "POST", "/api/vision/center-sweep/best", undefined],
    [() => api.centerSweepApply(10.5), "POST", "/api/vision/center-sweep/apply", { recoater_mm: 10.5 }],
    [() => api.centerSweepCancel(), "POST", "/api/vision/center-sweep/cancel", undefined],
  ];
  for (const [fn, method, path, body] of cases) {
    const c = await last(fn);
    assert.equal(c.method, method, path);
    assert.equal(c.url, path);
    assert.deepEqual(c.body, body, path);
    if (method !== "GET") assert.equal(c.headers[CLIENT_HEADER], "1", `${path} must carry the client header`);
    else assert.equal(c.headers[CLIENT_HEADER], undefined);
  }
});

test("errors carry status and FastAPI detail", async () => {
  (globalThis as unknown as { fetch: typeof fetch }).fetch = (async () => new Response(JSON.stringify({ detail: "not armed" }), { status: 409 })) as typeof fetch;
  await assert.rejects(api.arm(), (e: Error) => /409 not armed/.test(e.message));
});

test("layer url", async () => {
  const { api: a } = await import("./api.ts");
  assert.equal(a.jobLayerUrl(7, "20260505_x"), "/api/jobs/current/layers/7.png?job=20260505_x");
});
