import assert from "node:assert/strict";
import { test } from "node:test";
import {
  hiddenReason,
  ignoreDevice,
  inventoryRows,
  isIgnoredInput,
  loadIgnoreSet,
  saveIgnoredNames,
  scrubHiddenSelections,
  unignoreDevice,
  type IgnoreSet,
} from "./camera_ignore.ts";
import { loadRoleMap, saveRoleMap } from "./camera_roles.ts";
import { loadLiveFeedCameraId, saveLiveFeedCameraId } from "./live_feed.ts";
import type { VideoInput } from "./webcam.ts";

function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() { return data.size; },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    removeItem: (key) => { data.delete(key); },
    setItem: (key, value) => { data.set(key, value); },
  };
}

// Server names captured from this Mac's real /api/vision/avf-cameras (2026-09-23); Chrome appends a
// "(vid:pid)" suffix to USB camera labels, hence label-CONTAINS-name matching.
const ELP_A: VideoInput = { deviceId: "elpA", label: "ELP 4K USB Camera (32e4:9230)" };
const ELP_B: VideoInput = { deviceId: "elpB", label: "ELP 4K USB Camera (32e4:9230)" };
const FACETIME: VideoInput = { deviceId: "ft", label: "FaceTime HD Camera" };
const MACBOOK: VideoInput = { deviceId: "mbp", label: "MacBook Pro Camera" };
const NONE: IgnoreSet = { deviceIds: [], names: [] };

test("an ignore set loads empty from empty/absent storage", () => {
  assert.deepEqual(loadIgnoreSet(null), NONE);
  assert.deepEqual(loadIgnoreSet(memoryStorage()), NONE);
});

test("per-device ignore persists and un-ignores", () => {
  const s = memoryStorage();
  ignoreDevice(s, "elpB");
  ignoreDevice(s, "elpB"); // idempotent
  assert.deepEqual(loadIgnoreSet(s).deviceIds, ["elpB"]);
  unignoreDevice(s, "elpB");
  assert.deepEqual(loadIgnoreSet(s).deviceIds, []);
});

test("server names are cached for synchronous filtering", () => {
  const s = memoryStorage();
  saveIgnoredNames(s, ["FaceTime HD Camera", ""]);
  assert.deepEqual(loadIgnoreSet(s).names, ["FaceTime HD Camera"]);
});

test("junk in storage never throws and yields an empty set", () => {
  const s = memoryStorage();
  s.setItem("vpi.ignoredCameraDeviceIds", "{not json");
  s.setItem("vpi.ignoredCameraNames", JSON.stringify({ a: 1 }));
  assert.deepEqual(loadIgnoreSet(s), NONE);
});

test("an input is ignored by its deviceId or by a label containing an ignored name", () => {
  const ig: IgnoreSet = { deviceIds: ["elpB"], names: ["facetime hd camera"] };
  assert.equal(isIgnoredInput(ELP_B, ig), true);
  assert.equal(isIgnoredInput(ELP_A, ig), false); // its identical twin stays visible
  assert.equal(isIgnoredInput(FACETIME, ig), true); // case-insensitive name match
  assert.equal(isIgnoredInput({ deviceId: "x", label: "" }, { deviceIds: [], names: [""] }), false);
});

test("hiddenReason says why a camera is hidden: ignored beats built-in", () => {
  const ig: IgnoreSet = { deviceIds: [], names: ["FaceTime HD Camera"] };
  assert.equal(hiddenReason(FACETIME, ig), "ignored");
  assert.equal(hiddenReason(MACBOOK, ig), "built-in");
  assert.equal(hiddenReason(ELP_A, ig), null);
});

test("scrub clears saved role and live-feed ids that point at a hidden camera", () => {
  const s = memoryStorage();
  saveRoleMap(s, { overview: "ft", science: "elpB" });
  saveLiveFeedCameraId(s, "ft");
  ignoreDevice(s, "elpB");
  const cleared = scrubHiddenSelections(s, [ELP_A, ELP_B, FACETIME], loadIgnoreSet(s));
  assert.deepEqual(cleared.sort(), ["vpi.liveFeedCameraId", "vpi.overviewCameraId", "vpi.scienceCameraId"]);
  assert.deepEqual(loadRoleMap(s), { overview: null, science: null });
  assert.equal(loadLiveFeedCameraId(s), null);
});

test("scrub keeps a visible selection and ids it cannot see (unplugged)", () => {
  const s = memoryStorage();
  saveRoleMap(s, { overview: "elpA", science: "unplugged" });
  assert.deepEqual(scrubHiddenSelections(s, [ELP_A, FACETIME], NONE), []);
  assert.deepEqual(loadRoleMap(s), { overview: "elpA", science: "unplugged" });
});

test("inventoryRows lists every camera with why it is hidden and whether this browser hid it", () => {
  const ig: IgnoreSet = { deviceIds: ["elpB"], names: ["FaceTime HD Camera"] };
  assert.deepEqual(inventoryRows([ELP_A, ELP_B, FACETIME, MACBOOK], ig), [
    { deviceId: "elpA", label: ELP_A.label, display: `${ELP_A.label} #1`, reason: null, ignoredHere: false },
    { deviceId: "elpB", label: ELP_B.label, display: `${ELP_B.label} #2`, reason: "ignored", ignoredHere: true },
    { deviceId: "ft", label: "FaceTime HD Camera", display: "FaceTime HD Camera", reason: "ignored", ignoredHere: false },
    { deviceId: "mbp", label: "MacBook Pro Camera", display: "MacBook Pro Camera", reason: "built-in", ignoredHere: false },
  ]);
});
