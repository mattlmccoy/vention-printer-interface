import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_OVERVIEW_SETTINGS,
  defaultSettingsFor,
  loadCameraSettings,
  loadOverviewSettings,
  resolutionsFor,
  resolutionWH,
  RESOLUTIONS,
  saveCameraSettings,
  saveOverviewSettings,
  videoConstraints,
} from "./overview_settings.ts";

function memStorage(): Storage {
  const m = new Map<string, string>();
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
    clear: () => m.clear(),
    key: () => null,
    length: 0,
  } as unknown as Storage;
}

test("default overview settings are 4K @ 30", () => {
  assert.equal(DEFAULT_OVERVIEW_SETTINGS.resolution, "3840x2160");
  assert.equal(DEFAULT_OVERVIEW_SETTINGS.frameRate, 30);
  // 4K / 1080p / 720p are all offered
  assert.deepEqual(RESOLUTIONS.map((r) => r.key), ["3840x2160", "1920x1080", "1280x720"]);
});

test("resolutionsFor: overview tops out at 4K; science offers extra-high-res up to 20MP", () => {
  assert.deepEqual(resolutionsFor("overview").map((r) => r.key), ["3840x2160", "1920x1080", "1280x720"]);
  const sci = resolutionsFor("science").map((r) => r.key);
  assert.equal(sci[0], "5120x3840"); // 20MP first — the science camera's native still resolution
  assert.ok(sci.includes("2560x1440"));
  assert.ok(sci.includes("3840x2160"));
});

test("defaultSettingsFor: overview 4K@30; science defaults to a streamable res (20MP is opt-in)", () => {
  assert.deepEqual(defaultSettingsFor("overview"), { resolution: "3840x2160", frameRate: 30, manual: {} });
  const sci = defaultSettingsFor("science");
  assert.equal(sci.frameRate, 30);
  // not 20MP by default — a 20MP live preview may not stream; it's selectable for capture
  assert.notEqual(sci.resolution, "5120x3840");
  assert.ok(resolutionsFor("science").some((r) => r.key === sci.resolution));
});

test("resolutionWH parses ANY WxH key (incl. 20MP), falls back to 4K for junk", () => {
  assert.deepEqual(resolutionWH("1920x1080"), { width: 1920, height: 1080 });
  assert.deepEqual(resolutionWH("5120x3840"), { width: 5120, height: 3840 });
  assert.deepEqual(resolutionWH("nonsense"), { width: 3840, height: 2160 });
});

test("loadCameraSettings defaults per role (science default is a science resolution)", () => {
  assert.deepEqual(loadCameraSettings(null, "science"), defaultSettingsFor("science"));
  assert.deepEqual(loadCameraSettings(null, "overview"), defaultSettingsFor("overview"));
});

test("videoConstraints builds an exact-device, ideal-res/fps request", () => {
  const c = videoConstraints("devA", { resolution: "1920x1080", frameRate: 24, manual: {} });
  assert.deepEqual(c, {
    deviceId: { exact: "devA" },
    width: { ideal: 1920 },
    height: { ideal: 1080 },
    frameRate: { ideal: 24 },
  });
});

test("load returns defaults with no storage / empty storage, and merges a partial saved blob", () => {
  assert.deepEqual(loadOverviewSettings(null), DEFAULT_OVERVIEW_SETTINGS);
  const s = memStorage();
  assert.deepEqual(loadOverviewSettings(s), DEFAULT_OVERVIEW_SETTINGS);
  // a saved blob missing frameRate keeps the default frameRate
  s.setItem("vpi.overviewSettings", JSON.stringify({ resolution: "1280x720" }));
  const loaded = loadOverviewSettings(s);
  assert.equal(loaded.resolution, "1280x720");
  assert.equal(loaded.frameRate, 30);
  assert.deepEqual(loaded.manual, {});
});

test("overview and science settings persist under separate keys, both default 4K@30", () => {
  const s = memStorage();
  // both default before anything is saved
  assert.equal(loadCameraSettings(s, "overview").resolution, "3840x2160");
  assert.equal(loadCameraSettings(s, "science").resolution, "3840x2160");
  saveCameraSettings(s, "science", { resolution: "1920x1080", frameRate: 15, manual: { exposureTime: 800 } });
  saveCameraSettings(s, "overview", { resolution: "3840x2160", frameRate: 30, manual: {} });
  // independent
  assert.equal(loadCameraSettings(s, "science").resolution, "1920x1080");
  assert.equal(loadCameraSettings(s, "science").frameRate, 15);
  assert.deepEqual(loadCameraSettings(s, "science").manual, { exposureTime: 800 });
  assert.equal(loadCameraSettings(s, "overview").resolution, "3840x2160");
  // loadOverviewSettings is the overview alias
  assert.deepEqual(loadOverviewSettings(s), loadCameraSettings(s, "overview"));
});

test("save then load round-trips", () => {
  const s = memStorage();
  saveOverviewSettings(s, { resolution: "3840x2160", frameRate: 30, manual: { exposureTime: 500 } });
  assert.deepEqual(loadOverviewSettings(s), {
    resolution: "3840x2160",
    frameRate: 30,
    manual: { exposureTime: 500 },
  });
});
