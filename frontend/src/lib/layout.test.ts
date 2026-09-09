import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_LAYOUT, RAIL_W, layoutReducer, loadLayout, saveLayout } from "./layout.ts";

class Mem implements Storage {
  m = new Map<string, string>();
  get length() { return this.m.size; }
  clear() { this.m.clear(); }
  getItem(k: string) { return this.m.get(k) ?? null; }
  key(i: number) { return [...this.m.keys()][i] ?? null; }
  removeItem(k: string) { this.m.delete(k); }
  setItem(k: string, v: string) { this.m.set(k, v); }
}

test("reducer never mutates and clamps sizes", () => {
  const s = layoutReducer(DEFAULT_LAYOUT, { type: "setRailW", w: 5000 });
  assert.equal(s.railW, RAIL_W.max);
  assert.equal(DEFAULT_LAYOUT.railW, RAIL_W.default);
  assert.equal(layoutReducer(DEFAULT_LAYOUT, { type: "setRailW", w: RAIL_W.default + 5 }).railW, RAIL_W.default);
  assert.equal(layoutReducer(DEFAULT_LAYOUT, { type: "setPlotWindow", s: 999 }).plotWindowS, 120);
  assert.equal(layoutReducer(DEFAULT_LAYOUT, { type: "setPlotWindow", s: 600 }).plotWindowS, 600);
});

test("persistence validates every field", () => {
  const st = new Mem();
  st.setItem("vpi.layout.v1", JSON.stringify({ tool: "nope", railW: "x", sections: { axes: false }, floating: { axes: { x: 1, y: 2, w: 10, h: 10 } } }));
  const l = loadLayout(st);
  assert.equal(l.tool, "jog");
  assert.equal(l.railW, RAIL_W.default);
  assert.equal(l.sections.axes, false);
  assert.equal(l.sections.recipe, true);
  assert.deepEqual(l.floating.axes, { x: 1, y: 2, w: 260, h: 160 });
  st.setItem("vpi.layout.v1", "garbage");
  assert.equal(loadLayout(st), DEFAULT_LAYOUT);
  saveLayout(st, { ...DEFAULT_LAYOUT, tool: "home" });
  assert.equal(loadLayout(st).tool, "home");
});
