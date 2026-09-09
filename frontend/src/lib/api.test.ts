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
    [() => api.recipe(), "GET", "/api/recipe", undefined],
    [() => api.setRecipe({ heater_enabled: true }), "PUT", "/api/recipe", { heater_enabled: true }],
    [() => api.recipeStart({ dry_run: true, single_step: false }), "POST", "/api/recipe/start", { dry_run: true, single_step: false }],
    [() => api.recipePause(), "POST", "/api/recipe/pause", undefined],
    [() => api.recipeResume(), "POST", "/api/recipe/resume", undefined],
    [() => api.recipeStep(), "POST", "/api/recipe/step", undefined],
    [() => api.recipeAbort(), "POST", "/api/recipe/abort", undefined],
    [() => api.recordingStart({ name: "a", notes: "" }), "POST", "/api/recording/start", { name: "a", notes: "" }],
    [() => api.recordingStop(), "POST", "/api/recording/stop", undefined],
    [() => api.recordings(), "GET", "/api/recordings", undefined],
    [() => api.macro("load_cart"), "POST", "/api/macro/load_cart", undefined],
    [() => api.events(), "GET", "/api/events", undefined],
    [() => api.autoLog(), "GET", "/api/auto-log", undefined],
    [() => api.setAutoLog(false), "PUT", "/api/auto-log", { enabled: false }],
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
