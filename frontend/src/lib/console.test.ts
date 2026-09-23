import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_CONSOLE, VIEWS, clampSize, loadConsole, moduleOrder, moveModule, saveConsole } from "./console.ts";

test("VIEWS registers the cameras view", () => {
  assert.ok(VIEWS.includes("cameras"), "VIEWS must include \"cameras\" for the Cameras tab");
});

class Mem implements Storage {
  m = new Map<string, string>();
  get length() { return this.m.size; }
  clear() { this.m.clear(); }
  getItem(k: string) { return this.m.get(k) ?? null; }
  key(i: number) { return [...this.m.keys()][i] ?? null; }
  removeItem(k: string) { this.m.delete(k); }
  setItem(k: string, v: string) { this.m.set(k, v); }
}

test("console state validates on load", () => {
  const st = new Mem();
  st.setItem("vpi.console.v1", JSON.stringify({ view: "nope", gantryStep: 7, pistonStep: 100, order: { print: ["b", 3, "a"], junk: ["x"] }, readOnlyConnect: "yes" }));
  const c = loadConsole(st);
  assert.equal(c.view, "job"); assert.equal(c.gantryStep, 10); assert.equal(c.pistonStep, 100);
  assert.deepEqual(c.order, { print: ["b", "a"] });
  assert.deepEqual(c.sizes, {});
  assert.equal(c.readOnlyConnect, false);
  saveConsole(st, { ...DEFAULT_CONSOLE, view: "control" });
  assert.equal(loadConsole(st).view, "control");
  st.setItem("vpi.console.v1", "x");
  assert.equal(loadConsole(st), DEFAULT_CONSOLE);
});

test("module order merges saved order with known ids", () => {
  assert.deepEqual(moduleOrder(undefined, ["a", "b"]), ["a", "b"]);
  assert.deepEqual(moduleOrder(["b", "zz"], ["a", "b", "c"]), ["b", "a", "c"]);
});

test("moveModule is pure and places before the target", () => {
  const o = ["a", "b", "c"];
  assert.deepEqual(moveModule(o, "c", "a"), ["c", "a", "b"]);
  assert.deepEqual(moveModule(o, "a", null), ["b", "c", "a"]);
  assert.deepEqual(moveModule(o, "a", "a"), o);
  assert.deepEqual(o, ["a", "b", "c"]);
});

test("clampSize keeps sizes in bounds and rounds", () => {
  assert.deepEqual(clampSize(10, 10), { w: 240, h: 120 });
  assert.deepEqual(clampSize(9999, 9999), { w: 1400, h: 900 });
  assert.deepEqual(clampSize(460.6, 300.4), { w: 461, h: 300 });
});

test("sizes round-trip and drop malformed entries", () => {
  const st = new Mem();
  saveConsole(st, { ...DEFAULT_CONSOLE, sizes: { print: { run: { w: 500, h: 300 } } } });
  assert.deepEqual(loadConsole(st).sizes.print, { run: { w: 500, h: 300 } });
  // invalid views are dropped; entries missing w or h are dropped; a view left empty is omitted
  st.setItem("vpi.console.v1", JSON.stringify({ sizes: { print: { a: { w: 500 } }, junk: { x: { w: 1, h: 1 } }, control: { m: { w: 1, h: 1 } } } }));
  assert.deepEqual(loadConsole(st).sizes, { control: { m: { w: 240, h: 120 } } });
});

test("5 mm is a jog step on the Controls page, and a saved 5 mm step survives a reload", async () => {
  const { JOG_STEPS } = await import("./console.ts");
  assert.ok((JOG_STEPS as readonly number[]).includes(5));
  const mem = new Map<string, string>();
  const storage = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => void mem.set(k, v) } as unknown as Storage;
  saveConsole(storage, { ...DEFAULT_CONSOLE, gantryStep: 5, pistonStep: 5 });
  const back = loadConsole(storage);
  assert.equal(back.gantryStep, 5);
  assert.equal(back.pistonStep, 5);
});
