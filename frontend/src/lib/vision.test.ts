import { test } from "node:test";
import assert from "node:assert/strict";
import { formatCaptureMetaValue, overviewStreamUrl, panelVisible, parseCaptures, setPanelVisible } from "./vision.ts";

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

// Fixture shape captured from the real, enriched manifest record the backend now returns from
// GET /api/vision/captures — see backend/vention_printer_interface/api/app.py's vision_captures
// (append_manifest's {run_id, layer, stage, registered, host_timestamp_ns} plus the url/
// sidecar_url fields added by _vision_file_url/_sidecar_rel_path). Captured verbatim by running:
//   uv run python -c "from vention_printer_interface.api.app import _vision_file_url; \
//     print(_vision_file_url('r1', 'vision/layer_0001/pre_jet.png'))"
// -> "/api/vision/runs/r1/file?path=vision%2Flayer_0001%2Fpre_jet.png"
test("parseCaptures maps manifest records and sorts by layer then stage order", () => {
  const manifest = [
    {
      run_id: "r1", layer: 2, stage: "pre_jet", registered: "vision/layer_0002/pre_jet.png", host_timestamp_ns: 5,
      url: "/api/vision/runs/r1/file?path=vision%2Flayer_0002%2Fpre_jet.png",
      sidecar_url: "/api/vision/runs/r1/file?path=vision%2Flayer_0002%2Fpre_jet.json",
    },
    {
      run_id: "r1", layer: 1, stage: "post_heat", registered: "vision/layer_0001/post_heat.png", host_timestamp_ns: 3,
      url: "/api/vision/runs/r1/file?path=vision%2Flayer_0001%2Fpost_heat.png",
      sidecar_url: "/api/vision/runs/r1/file?path=vision%2Flayer_0001%2Fpost_heat.json",
    },
    {
      run_id: "r1", layer: 1, stage: "pre_jet", registered: "vision/layer_0001/pre_jet.png", host_timestamp_ns: 1,
      url: "/api/vision/runs/r1/file?path=vision%2Flayer_0001%2Fpre_jet.png",
      sidecar_url: "/api/vision/runs/r1/file?path=vision%2Flayer_0001%2Fpre_jet.json",
    },
    {
      run_id: "r1", layer: 1, stage: "post_jet", registered: "vision/layer_0001/post_jet.png", host_timestamp_ns: 2,
      url: "/api/vision/runs/r1/file?path=vision%2Flayer_0001%2Fpost_jet.png",
      sidecar_url: "/api/vision/runs/r1/file?path=vision%2Flayer_0001%2Fpost_jet.json",
    },
  ];
  assert.deepEqual(parseCaptures(manifest), [
    { layer: 1, stage: "pre_jet", url: "/api/vision/runs/r1/file?path=vision%2Flayer_0001%2Fpre_jet.png", sidecarUrl: "/api/vision/runs/r1/file?path=vision%2Flayer_0001%2Fpre_jet.json" },
    { layer: 1, stage: "post_jet", url: "/api/vision/runs/r1/file?path=vision%2Flayer_0001%2Fpost_jet.png", sidecarUrl: "/api/vision/runs/r1/file?path=vision%2Flayer_0001%2Fpost_jet.json" },
    { layer: 1, stage: "post_heat", url: "/api/vision/runs/r1/file?path=vision%2Flayer_0001%2Fpost_heat.png", sidecarUrl: "/api/vision/runs/r1/file?path=vision%2Flayer_0001%2Fpost_heat.json" },
    { layer: 2, stage: "pre_jet", url: "/api/vision/runs/r1/file?path=vision%2Flayer_0002%2Fpre_jet.png", sidecarUrl: "/api/vision/runs/r1/file?path=vision%2Flayer_0002%2Fpre_jet.json" },
  ]);
});

test("parseCaptures falls back to the bare `registered` path when the backend url is absent", () => {
  // Prior-behavior fallback: an older, un-enriched record (or a test fixture) without url/
  // sidecar_url must still parse instead of being dropped.
  const manifest = [
    { run_id: "r1", layer: 1, stage: "pre_jet", registered: "vision/layer_0001/pre_jet.png", host_timestamp_ns: 1 },
  ];
  assert.deepEqual(parseCaptures(manifest), [
    { layer: 1, stage: "pre_jet", url: "vision/layer_0001/pre_jet.png" },
  ]);
});

test("parseCaptures tolerates malformed / unknown records instead of throwing", () => {
  const manifest: unknown[] = [
    {
      run_id: "r1", layer: 1, stage: "pre_jet", registered: "vision/layer_0001/pre_jet.png", host_timestamp_ns: 1,
      url: "/api/vision/runs/r1/file?path=vision%2Flayer_0001%2Fpre_jet.png",
      sidecar_url: "/api/vision/runs/r1/file?path=vision%2Flayer_0001%2Fpre_jet.json",
    },
    null,
    "junk",
    { layer: 2 }, // missing stage/registered/url
    { run_id: "r1", layer: "3", stage: "pre_jet", registered: "x.png" }, // layer not a number
  ];
  assert.deepEqual(parseCaptures(manifest), [
    { layer: 1, stage: "pre_jet", url: "/api/vision/runs/r1/file?path=vision%2Flayer_0001%2Fpre_jet.png", sidecarUrl: "/api/vision/runs/r1/file?path=vision%2Flayer_0001%2Fpre_jet.json" },
  ]);
});

// Pure formatting core for the capture browser's sidecar-metadata display (CamerasView's
// CaptureMeta): honest "—" for absent values, no invented data (data-contract-verification).
test("formatCaptureMetaValue shows — for null/undefined and formats present values", () => {
  assert.equal(formatCaptureMetaValue(null), "—");
  assert.equal(formatCaptureMetaValue(undefined), "—");
  assert.equal(formatCaptureMetaValue(3.5), "3.5");
  assert.equal(formatCaptureMetaValue(0), "0");
  assert.equal(formatCaptureMetaValue("post_jet"), "post_jet");
  assert.equal(formatCaptureMetaValue({ build: 12.5 }), '{"build":12.5}');
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
