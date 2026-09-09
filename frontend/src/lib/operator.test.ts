import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_SITE_BASE, checkHandshake, loadOperatorBase, normalizeBase, saveOperatorBase, wsUrl } from "./operator.ts";

class Mem implements Storage {
  m = new Map<string, string>();
  get length() { return this.m.size; }
  clear() { this.m.clear(); }
  getItem(k: string) { return this.m.get(k) ?? null; }
  key(i: number) { return [...this.m.keys()][i] ?? null; }
  removeItem(k: string) { this.m.delete(k); }
  setItem(k: string, v: string) { this.m.set(k, v); }
}

test("normalize + defaults", () => {
  assert.equal(DEFAULT_SITE_BASE, "http://localhost:8020");
  assert.equal(normalizeBase(" http://localhost:8020/ "), "http://localhost:8020");
  assert.equal(normalizeBase(""), "");
  assert.equal(normalizeBase("ftp://x"), null);
  assert.equal(loadOperatorBase(new Mem(), { siteMode: true }), DEFAULT_SITE_BASE);
  assert.equal(loadOperatorBase(new Mem(), { siteMode: false }), "");
  const st = new Mem();
  saveOperatorBase(st, "http://127.0.0.1:8020");
  assert.equal(st.getItem("vpi.operator.v1"), "http://127.0.0.1:8020");
});

test("ws url and handshake", () => {
  assert.equal(wsUrl("http://localhost:8020", "/ws/telemetry"), "ws://localhost:8020/ws/telemetry");
  assert.equal(wsUrl("", "/ws/x", { protocol: "https:", host: "h" }), "wss://h/ws/x");
  assert.equal(checkHandshake("0.1", "0.1").level, "ok");
  assert.equal(checkHandshake("0.1", "0.2").level, "warn");
  assert.equal(checkHandshake("0.1", "1.0").level, "refuse");
});
