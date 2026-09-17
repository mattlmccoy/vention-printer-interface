import { test } from "node:test";
import assert from "node:assert/strict";
import {
  isBuiltinOrPhoneLabel,
  pickOverviewDeviceId,
  videoInputs,
  type VideoInput,
} from "./webcam.ts";

const DEVS = [
  { kind: "audioinput", deviceId: "a1", label: "Mic" },
  { kind: "videoinput", deviceId: "elp", label: "20MP U3 Camera (32e4:2020)" },
  { kind: "videoinput", deviceId: "ft", label: "FaceTime HD Camera" },
  { kind: "videoinput", deviceId: "iphone", label: "mattmccoy's iPhone Camera" },
];

test("videoInputs keeps only cameras", () => {
  assert.deepEqual(
    videoInputs(DEVS).map((d) => d.deviceId),
    ["elp", "ft", "iphone"],
  );
});

test("isBuiltinOrPhoneLabel flags FaceTime / iPhone / Desk View, not the ELP", () => {
  assert.equal(isBuiltinOrPhoneLabel("FaceTime HD Camera"), true);
  assert.equal(isBuiltinOrPhoneLabel("mattmccoy's iPhone Camera"), true);
  assert.equal(isBuiltinOrPhoneLabel("iPhone Desk View Camera"), true);
  assert.equal(isBuiltinOrPhoneLabel("20MP U3 Camera (32e4:2020)"), false);
});

test("pickOverviewDeviceId honours a still-present saved selection first", () => {
  const inputs = videoInputs(DEVS);
  assert.equal(pickOverviewDeviceId(inputs, "elp", null), "elp");
  // saved id no longer plugged in -> fall through to the other rules
  assert.equal(pickOverviewDeviceId(inputs, "gone", "20MP U3"), "elp");
});

test("pickOverviewDeviceId matches the assigned name and never a phone/built-in", () => {
  const inputs = videoInputs(DEVS);
  // even though the iPhone/FaceTime sort first, the name hint picks the ELP
  assert.equal(pickOverviewDeviceId(inputs, null, "20MP U3 Camera"), "elp");
});

test("pickOverviewDeviceId auto-picks the only real camera when unambiguous", () => {
  const inputs: VideoInput[] = [
    { deviceId: "ft", label: "FaceTime HD Camera" },
    { deviceId: "iphone", label: "iPhone Camera" },
    { deviceId: "elp", label: "20MP U3 Camera" },
  ];
  assert.equal(pickOverviewDeviceId(inputs, null, null), "elp"); // only non-phone/built-in
});

test("pickOverviewDeviceId asks to pick when two real cameras are ambiguous", () => {
  const inputs: VideoInput[] = [
    { deviceId: "elpA", label: "20MP U3 Camera (32e4:2020)" },
    { deviceId: "elpB", label: "20MP U3 Camera (32e4:2020)" },
  ];
  assert.equal(pickOverviewDeviceId(inputs, null, null), null); // two identical ELPs -> user picks
});
