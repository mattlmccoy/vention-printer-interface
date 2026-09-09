import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_CONSOLE, loadConsole, saveConsole } from "./console.ts";

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
  st.setItem("vpi.console.v1", JSON.stringify({ view: "nope", gantryStep: 7, pistonStep: 100 }));
  const c = loadConsole(st);
  assert.equal(c.view, "print"); assert.equal(c.gantryStep, 10); assert.equal(c.pistonStep, 100);
  saveConsole(st, { ...DEFAULT_CONSOLE, view: "control" });
  assert.equal(loadConsole(st).view, "control");
  st.setItem("vpi.console.v1", "x");
  assert.equal(loadConsole(st), DEFAULT_CONSOLE);
});
