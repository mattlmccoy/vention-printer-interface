import assert from "node:assert/strict";
import { test } from "node:test";
import { loadRoleMap, saveRoleMap } from "./camera_roles.ts";
import { loadLiveFeedCameraId, saveLiveFeedCameraId } from "./live_feed.ts";

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

test("dock selection is independent of overview/science role assignments", () => {
  const storage = memoryStorage();
  saveRoleMap(storage, { overview: "wide", science: "bed" });
  assert.equal(loadLiveFeedCameraId(storage), "wide");
  saveLiveFeedCameraId(storage, "bed");
  assert.equal(loadLiveFeedCameraId(storage), "bed");
  assert.deepEqual(loadRoleMap(storage), { overview: "wide", science: "bed" });
});
