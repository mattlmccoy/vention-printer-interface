import { test } from "node:test";
import assert from "node:assert/strict";
import { overviewStreamUrl, panelVisible, parseCaptures, setPanelVisible } from "./vision.ts";

class Mem implements Storage {
  m = new Map<string, string>();
  get length() { return this.m.size; }
  clear() { this.m.clear(); }
  getItem(k: string) { return this.m.get(k) ?? null; }
  key(i: number) { return [...this.m.keys()][i] ?? null; }
  removeItem(k: string) { this.m.delete(k); }
  setItem(k: string, v: string) { this.m.set(k, v); }
}

class ThrowingStorage implements Storage {
  get length() { return 0; }
  clear() { throw new Error("blocked"); }
  getItem(): string | null { throw new Error("blocked"); }
  key(): string | null { throw new Error("blocked"); }
  removeItem() { throw new Error("blocked"); }
  setItem(): void { throw new Error("blocked"); }
}

test("overviewStreamUrl joins the operator base with the MJPEG path", () => {
  assert.equal(overviewStreamUrl(""), "/api/vision/overview/stream");
  assert.equal(overviewStreamUrl("http://localhost:8020"), "http://localhost:8020/api/vision/overview/stream");
});

// Fixture shape captured from the real manifest record the backend writes — see
// backend/vention_printer_interface/vision/capture.py:152-160 (append_manifest call).
test("parseCaptures maps manifest records and sorts by layer then stage order", () => {
  const manifest = [
    { run_id: "r1", layer: 2, stage: "pre_jet", registered: "vision/layer_0002/pre_jet.png", host_timestamp_ns: 5 },
    { run_id: "r1", layer: 1, stage: "post_heat", registered: "vision/layer_0001/post_heat.png", host_timestamp_ns: 3 },
    { run_id: "r1", layer: 1, stage: "pre_jet", registered: "vision/layer_0001/pre_jet.png", host_timestamp_ns: 1 },
    { run_id: "r1", layer: 1, stage: "post_jet", registered: "vision/layer_0001/post_jet.png", host_timestamp_ns: 2 },
  ];
  assert.deepEqual(parseCaptures(manifest), [
    { layer: 1, stage: "pre_jet", url: "vision/layer_0001/pre_jet.png" },
    { layer: 1, stage: "post_jet", url: "vision/layer_0001/post_jet.png" },
    { layer: 1, stage: "post_heat", url: "vision/layer_0001/post_heat.png" },
    { layer: 2, stage: "pre_jet", url: "vision/layer_0002/pre_jet.png" },
  ]);
});

test("parseCaptures tolerates malformed / unknown records instead of throwing", () => {
  const manifest: unknown[] = [
    { run_id: "r1", layer: 1, stage: "pre_jet", registered: "vision/layer_0001/pre_jet.png", host_timestamp_ns: 1 },
    null,
    "junk",
    { layer: 2 }, // missing stage/registered
    { run_id: "r1", layer: "3", stage: "pre_jet", registered: "x.png" }, // layer not a number
  ];
  assert.deepEqual(parseCaptures(manifest), [
    { layer: 1, stage: "pre_jet", url: "vision/layer_0001/pre_jet.png" },
  ]);
});

test("panelVisible defaults to true and persists per view via injected storage", () => {
  const st = new Mem();
  assert.equal(panelVisible("control", st), true);
  setPanelVisible("control", false, st);
  assert.equal(panelVisible("control", st), false);
  assert.equal(panelVisible("print", st), true); // other views unaffected
  setPanelVisible("print", false, st);
  assert.equal(panelVisible("control", st), false);
  assert.equal(panelVisible("print", st), false);
});

test("panelVisible/setPanelVisible tolerate a storage that throws", () => {
  const st = new ThrowingStorage();
  assert.equal(panelVisible("control", st), true);
  assert.doesNotThrow(() => setPanelVisible("control", false, st));
  assert.equal(panelVisible("control", null), true);
  assert.doesNotThrow(() => setPanelVisible("control", false, null));
});
