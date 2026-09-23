import { test } from "node:test";
import assert from "node:assert/strict";
import {
  allVideoInputs,
  isBuiltinOrPhoneLabel,
  labelCandidates,
  overviewCandidates,
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

test("overviewCandidates returns the real cameras to preview, dropping phones/built-ins/unlabelled", () => {
  const inputs: VideoInput[] = [
    { deviceId: "elpA", label: "20MP U3 Camera (32e4:2020)" },
    { deviceId: "ft", label: "FaceTime HD Camera" },
    { deviceId: "iphone", label: "mattmccoy's iPhone Camera" },
    { deviceId: "elpB", label: "20MP U3 Camera (32e4:2020)" },
    { deviceId: "blank", label: "" }, // no label yet -> can't be shown/identified
  ];
  assert.deepEqual(
    overviewCandidates(inputs).map((d) => d.deviceId),
    ["elpA", "elpB"], // both identical ELPs, in enumeration order; phones + blank dropped
  );
});

test("overviewCandidates still returns a single real camera (tile confirms which one it is)", () => {
  const inputs: VideoInput[] = [
    { deviceId: "ft", label: "FaceTime HD Camera" },
    { deviceId: "elp", label: "20MP U3 Camera" },
  ];
  assert.deepEqual(overviewCandidates(inputs).map((d) => d.deviceId), ["elp"]);
});

test("labelCandidates numbers colliding labels so identical cameras are tellable apart", () => {
  const cams: VideoInput[] = [
    { deviceId: "elpA", label: "20MP U3 Camera (32e4:2020)" },
    { deviceId: "elpB", label: "20MP U3 Camera (32e4:2020)" },
  ];
  assert.deepEqual(
    labelCandidates(cams).map((c) => c.display),
    ["20MP U3 Camera (32e4:2020) #1", "20MP U3 Camera (32e4:2020) #2"],
  );
});

test("labelCandidates leaves a unique label untouched, numbers only the duplicates", () => {
  const cams: VideoInput[] = [
    { deviceId: "elpA", label: "20MP U3 Camera" },
    { deviceId: "wide", label: "Wide Cam" },
    { deviceId: "elpB", label: "20MP U3 Camera" },
  ];
  assert.deepEqual(
    labelCandidates(cams).map((c) => c.display),
    ["20MP U3 Camera #1", "Wide Cam", "20MP U3 Camera #2"],
  );
  // display is additive: original fields are preserved
  assert.equal(labelCandidates(cams)[0].deviceId, "elpA");
});

// ---- camera permission + getUserMedia error reasons (Windows: tiles were silently empty) -------
import { needsCameraPermission, cameraErrorMessage } from "./webcam.ts";

test("needsCameraPermission: cameras listed but every label hidden -> must ask", () => {
  // Browsers hide labels (and Chrome hides deviceIds) until the site is granted camera access.
  assert.equal(needsCameraPermission([{ kind: "videoinput", deviceId: "", label: "" }]), true);
  assert.equal(needsCameraPermission([
    { kind: "videoinput", deviceId: "", label: "" },
    { kind: "audioinput", deviceId: "a", label: "Mic" },
  ]), true);
});

test("needsCameraPermission: labels visible (granted) or no cameras at all -> no ask", () => {
  assert.equal(needsCameraPermission([{ kind: "videoinput", deviceId: "d", label: "ELP 4K USB Camera" }]), false);
  assert.equal(needsCameraPermission([{ kind: "audioinput", deviceId: "", label: "" }]), false);
  assert.equal(needsCameraPermission([]), false);
});

const err = (name: string, message = "") => Object.assign(new Error(message), { name });

test("cameraErrorMessage: blocked access names the browser AND the Windows privacy switch", () => {
  const m = cameraErrorMessage(err("NotAllowedError"));
  assert.match(m, /blocked/i);
  assert.match(m, /Let desktop apps access your camera/);
});

test("cameraErrorMessage: in-use camera says so (Windows lets one app hold a camera)", () => {
  assert.match(cameraErrorMessage(err("NotReadableError")), /in use/i);
  assert.match(cameraErrorMessage(err("TrackStartError")), /in use/i); // older Chrome name
});

test("cameraErrorMessage: missing / unsupported camera", () => {
  assert.match(cameraErrorMessage(err("NotFoundError")), /not (found|available)/i);
  assert.match(cameraErrorMessage(err("OverconstrainedError")), /not (found|available)|resolution/i);
});

test("cameraErrorMessage: unknown errors keep their name for diagnosis", () => {
  assert.match(cameraErrorMessage(err("WeirdError", "boom")), /WeirdError.*boom/);
  assert.match(cameraErrorMessage("nope"), /camera error/i);
});

// ---- ignored / built-in cameras never reach a picker ------------------------------------------

test("isBuiltinOrPhoneLabel flags every built-in laptop camera label, never a USB ELP", () => {
  assert.equal(isBuiltinOrPhoneLabel("FaceTime HD Camera"), true);
  assert.equal(isBuiltinOrPhoneLabel("MacBook Pro Camera"), true); // Apple-silicon Macs
  assert.equal(isBuiltinOrPhoneLabel("MacBook Air Camera"), true);
  assert.equal(isBuiltinOrPhoneLabel("Integrated Camera"), true); // Windows laptops
  assert.equal(isBuiltinOrPhoneLabel("FaceTime HD Camera (Built-in) (05ac:8514)"), true);
  assert.equal(isBuiltinOrPhoneLabel("ELP 4K USB Camera (32e4:9230)"), false);
  assert.equal(isBuiltinOrPhoneLabel("20MP U3 Camera (32e4:2020)"), false);
  assert.equal(isBuiltinOrPhoneLabel("USB Camera"), false);
});

test("videoInputs drops cameras on the ignore list (by name and by deviceId)", () => {
  const devs = [
    { kind: "videoinput", deviceId: "ft", label: "FaceTime HD Camera" },
    { kind: "videoinput", deviceId: "elpA", label: "ELP 4K USB Camera (32e4:9230)" },
    { kind: "videoinput", deviceId: "elpB", label: "ELP 4K USB Camera (32e4:9230)" },
  ];
  const ignore = { deviceIds: ["elpB"], names: ["FaceTime HD Camera"] };
  assert.deepEqual(videoInputs(devs, ignore).map((d) => d.deviceId), ["elpA"]);
  assert.deepEqual(allVideoInputs(devs).map((d) => d.deviceId), ["ft", "elpA", "elpB"]);
});

test("pickOverviewDeviceId never returns a saved built-in camera", () => {
  const inputs: VideoInput[] = [
    { deviceId: "ft", label: "FaceTime HD Camera" },
    { deviceId: "elp", label: "ELP 4K USB Camera (32e4:9230)" },
  ];
  assert.equal(pickOverviewDeviceId(inputs, "ft", null), "elp");
  assert.equal(pickOverviewDeviceId([inputs[0]], "ft", null), null);
});

test("pickOverviewDeviceId never returns a saved ignored camera", () => {
  const inputs: VideoInput[] = [
    { deviceId: "elpA", label: "ELP 4K USB Camera (32e4:9230)" },
    { deviceId: "elpB", label: "ELP 4K USB Camera (32e4:9230)" },
  ];
  const ignore = { deviceIds: ["elpB"], names: [] };
  assert.equal(pickOverviewDeviceId(inputs, "elpB", null, ignore), "elpA");
});
