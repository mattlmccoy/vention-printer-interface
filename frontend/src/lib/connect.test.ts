import { test } from "node:test";
import assert from "node:assert/strict";
import { connectOptions } from "./connect.ts";

test("keeps simulator + reachable MM, drops unreachable MM, always offers custom", () => {
  const cands = [
    { backend: "simulated", ip: null, label: "simulator", reachable: true },
    { backend: "machinemotion", ip: "192.168.0.2", label: "ethernet", reachable: false },
    { backend: "machinemotion", ip: "192.168.7.2", label: "usb", reachable: true },
  ];
  const opts = connectOptions(cands);
  assert.deepEqual(opts.map((o) => o.value), ["simulated", "usb", "custom"]);
  assert.match(opts[1].label, /USB.*192\.168\.7\.2/);
});

test("with no reachable MM, still offers simulator + custom", () => {
  const opts = connectOptions([{ backend: "simulated", ip: null, label: "simulator", reachable: true }]);
  assert.deepEqual(opts.map((o) => o.value), ["simulated", "custom"]);
});
