import { test } from "node:test";
import assert from "node:assert/strict";
import {
  assignRole,
  loadRoleMap,
  roleOf,
  saveRoleMap,
  type CameraRoleMap,
} from "./camera_roles.ts";

const EMPTY: CameraRoleMap = { overview: null, science: null };

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

test("assignRole sets a role on a free device", () => {
  assert.deepEqual(assignRole(EMPTY, "A", "overview"), { overview: "A", science: null });
  assert.deepEqual(assignRole({ overview: "A", science: null }, "B", "science"), { overview: "A", science: "B" });
});

test("assignRole moves a device from its old role (a camera can hold only one role)", () => {
  // A was overview; make it science -> it leaves overview.
  assert.deepEqual(assignRole({ overview: "A", science: null }, "A", "science"), { overview: null, science: "A" });
});

test("assignRole reassigning a role to a new device evicts the previous holder of that role", () => {
  assert.deepEqual(assignRole({ overview: "A", science: "B" }, "B", "overview"), { overview: "B", science: null });
});

test("assignRole with empty role clears whichever role the device held", () => {
  assert.deepEqual(assignRole({ overview: "A", science: "B" }, "A", ""), { overview: null, science: "B" });
  assert.deepEqual(assignRole({ overview: "A", science: "B" }, "B", ""), { overview: "A", science: null });
  // clearing a device that holds no role is a no-op
  assert.deepEqual(assignRole({ overview: "A", science: "B" }, "C", ""), { overview: "A", science: "B" });
});

test("roleOf reports a device's current role, or empty string", () => {
  const m: CameraRoleMap = { overview: "A", science: "B" };
  assert.equal(roleOf(m, "A"), "overview");
  assert.equal(roleOf(m, "B"), "science");
  assert.equal(roleOf(m, "C"), "");
});

test("legacy duplicate ids preserve science and require overview reassignment", () => {
  const storage = memoryStorage();
  saveRoleMap(storage, { overview: "bed", science: "bed" });
  assert.deepEqual(loadRoleMap(storage), { overview: null, science: "bed" });
});
