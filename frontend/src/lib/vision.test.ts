import { test } from "node:test";
import assert from "node:assert/strict";
import { calibrationReady, cameraAccessMessage, captureLayerFull, captureLayerShort, dismissQuickStart, formatCaptureMetaValue, formatValidation, overviewStreamUrl, panelVisible, parseCaptures, setPanelVisible, shouldShowQuickStart } from "./vision.ts";

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

test("captureLayerFull/Short differentiate the printing layer from the absolute build layer", () => {
  const printing = { layer: 6, cadLayer: 1, stage: "post_jet", url: "/u" };
  assert.equal(captureLayerFull(printing), "printing layer 1 · build layer 6");
  assert.equal(captureLayerShort(printing), "P1");
  // no printing index (e.g. an older capture): fall back to the absolute layer
  const bare = { layer: 3, stage: "pre_jet", url: "/u" };
  assert.equal(captureLayerFull(bare), "layer 3");
  assert.equal(captureLayerShort(bare), "L3");
});

test("parseCaptures reads the printing/CAD layer (cad_layer) when present, else undefined", () => {
  const [c] = parseCaptures([{ layer: 8, cad_layer: 3, stage: "post_jet", url: "/u" }]);
  assert.equal(c.cadLayer, 3);
  const [d] = parseCaptures([{ layer: 2, stage: "pre_jet", url: "/u" }]);
  assert.equal(d.cadLayer, undefined);
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

// shouldShowQuickStart (A7): gates the first-run camera-role wizard on GET /api/vision/status's
// roles_resolved/unresolved, and remembers a dismissal per the *set* of currently-unresolved
// roles (a "device-set" signature) so a later camera swap that leaves a different role
// unresolved re-opens the wizard instead of staying silently hidden forever.
test("shouldShowQuickStart is false when status is unknown (null) — never show on no data", () => {
  const st = new Mem();
  assert.equal(shouldShowQuickStart(null, st), false);
});

test("shouldShowQuickStart is false once every role is resolved", () => {
  const st = new Mem();
  assert.equal(shouldShowQuickStart({ roles_resolved: true, unresolved: [] }, st), false);
});

test("shouldShowQuickStart is true when unresolved and not yet dismissed", () => {
  const st = new Mem();
  assert.equal(
    shouldShowQuickStart({ roles_resolved: false, unresolved: ["overview", "science"] }, st),
    true,
  );
});

test("shouldShowQuickStart is false after dismissQuickStart for the same unresolved set", () => {
  const st = new Mem();
  const status = { roles_resolved: false, unresolved: ["overview", "science"] };
  dismissQuickStart(status, st);
  assert.equal(shouldShowQuickStart(status, st), false);
});

test("shouldShowQuickStart reopens when the unresolved device-set changes after a dismissal", () => {
  const st = new Mem();
  dismissQuickStart({ roles_resolved: false, unresolved: ["overview", "science"] }, st);
  // A camera got swapped: overview is now confirmed, but a NEW unresolved set (science only)
  // must not be silently swallowed by the old dismissal.
  assert.equal(shouldShowQuickStart({ roles_resolved: false, unresolved: ["science"] }, st), true);
});

test("shouldShowQuickStart dismissal is order-independent within the same unresolved set", () => {
  const st = new Mem();
  dismissQuickStart({ roles_resolved: false, unresolved: ["science", "overview"] }, st);
  assert.equal(
    shouldShowQuickStart({ roles_resolved: false, unresolved: ["overview", "science"] }, st),
    false,
  );
});

test("shouldShowQuickStart/dismissQuickStart tolerate a storage that throws", () => {
  const st = new ThrowingStorage();
  const status = { roles_resolved: false, unresolved: ["science"] };
  assert.equal(shouldShowQuickStart(status, st), true);
  assert.doesNotThrow(() => dismissQuickStart(status, st));
  assert.equal(shouldShowQuickStart(null, st), false);
});

// cameraAccessMessage (camera-permission signal from GET /api/vision/devices' camera_access,
// see backend vention_printer_interface/vision/cameras.py's camera_access_state): the user-
// facing string shown in place of an empty/silent device list when the OS is blocking access.
test("cameraAccessMessage explains a denied camera and points at System Settings", () => {
  assert.equal(
    cameraAccessMessage("denied"),
    "Camera permission not granted — enable it in System Settings → Privacy & Security → Camera, then rescan",
  );
});

test("cameraAccessMessage reports no cameras detected", () => {
  assert.match(cameraAccessMessage("no_devices"), /no camera/i);
});

test("cameraAccessMessage is empty/non-alarming when access is ok", () => {
  assert.doesNotMatch(cameraAccessMessage("ok"), /permission|not granted|denied/i);
});

// calibrationReady (guided calibration-capture session, GET/POST /api/vision/calibrate/session):
// n_views >= 3 (_MIN_CALIB_VIEWS in backend vention_printer_interface/api/app.py).
test("calibrationReady is false below 3 accumulated views", () => {
  assert.equal(calibrationReady({ n_views: 0 }), false);
  assert.equal(calibrationReady({ n_views: 2 }), false);
});

test("calibrationReady is true at 3 or more accumulated views", () => {
  assert.equal(calibrationReady({ n_views: 3 }), true);
  assert.equal(calibrationReady({ n_views: 5 }), true);
});

// formatValidation (POST /api/vision/validate's {rms_mm, max_mm, scale_bias, ...} result, see
// backend vention_printer_interface/api/app.py's vision_validate) scored against a +/-0.1mm
// dimensional target (protocol default) — max_mm within tolerance AND scale_bias within the
// same tolerance treated as a fraction (0.1 -> +/-10%), so a pure homography scale error (which
// the rigid, no-scale residual fit deliberately does not absorb) still fails validation.
test("formatValidation passes within the default 0.1mm / scale-bias tolerance", () => {
  const result = formatValidation({ rms_mm: 0.03, max_mm: 0.08, scale_bias: 1.02 });
  assert.deepEqual(result, { rmsMm: 0.03, maxMm: 0.08, scaleBias: 1.02, pass: true });
});

test("formatValidation fails when max_mm exceeds the tolerance", () => {
  const result = formatValidation({ rms_mm: 0.05, max_mm: 0.15, scale_bias: 1.0 });
  assert.equal(result.pass, false);
});

test("formatValidation fails when scale_bias drifts outside tolerance even with tiny residuals", () => {
  const result = formatValidation({ rms_mm: 0.01, max_mm: 0.02, scale_bias: 1.2 });
  assert.equal(result.pass, false);
});

test("formatValidation honors an explicit tolMm override", () => {
  const result = formatValidation({ rms_mm: 0.15, max_mm: 0.15, scale_bias: 1.1 }, 0.2);
  assert.equal(result.pass, true);
});
