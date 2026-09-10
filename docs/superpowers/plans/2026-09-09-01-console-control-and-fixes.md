# Console Control & Safe Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up the Control page and land the safe, unambiguous fixes from the redesign spec (§5, §10) so the operator gets a more readable, correct manual-driving page plus the small correctness fixes.

**Architecture:** Small, isolated changes to the existing React frontend (`frontend/src`) and FastAPI backend (`backend/vention_printer_interface`). Pure logic (travel constants, connect-option filtering, event humanization) is TDD'd; pure-UI changes are browser-verified against `--backend simulated`.

**Tech Stack:** Python 3.13 + `uv` + pytest + ruff + mypy (backend); Vite + React 18 + TS, `node --experimental-strip-types --test` (frontend).

Spec: `docs/superpowers/specs/2026-09-09-binderjet-console-redesign-design.md`.

---

## Task 1: Printhead soft-travel 840 → 970 mm

Mirror the recoater 972 change exactly, for the printhead extent (spec §10). Only the **travel extent** changes; the jet-pass target `printhead_end_mm` (840) stays a setting.

**Files:**
- Modify: `backend/vention_printer_interface/control/safety.py:18`
- Modify: `backend/vention_printer_interface/device/printer.py` (KNOWN_AXES axis 3)
- Modify: `backend/vention_printer_interface/device/simulated.py` (DEFAULT_AXES axis 3)
- Modify: `backend/vention_printer_interface/control/print_settings.py` (`_TRAVEL[PRINTHEAD]`)
- Modify: `frontend/src/lib/telemetry.ts:16`, `frontend/src/lib/estimate.ts:5`, `frontend/src/lib/print_settings.ts` (validate default `3: 840`), `frontend/src/lib/machine_calib.ts` ("840 mm" label)
- Test: `backend/tests/test_safety.py`, `frontend/src/lib/telemetry.test.ts`

- [ ] **Step 1: Write/adjust the failing frontend test**

In `frontend/src/lib/telemetry.test.ts` change the travel assertion:

```ts
  assert.deepEqual(TRAVEL_MM, { 1: 145, 2: 145, 3: 970, 4: 972 });
```

- [ ] **Step 2: Run it, verify it fails**

Run: `cd frontend && node --experimental-strip-types --test src/lib/telemetry.test.ts`
Expected: FAIL (actual `3: 840`).

- [ ] **Step 3: Change the constants (backend + frontend)**

`safety.py:18`:
```python
TRAVEL_MM: dict[int, float] = {1: 145.0, 2: 145.0, 3: 970.0, 4: 972.0}  # printhead/recoater end stops (2026-09-09)
```
`printer.py` KNOWN_AXES and `simulated.py` DEFAULT_AXES axis 3 tuple:
```python
    3: ("Printhead Gantry", 970.0, 66.3),
```
`print_settings.py` `_TRAVEL`:
```python
_TRAVEL = {PART: 145.0, FEED: 145.0, PRINTHEAD: 970.0, RECOATER: 972.0}
```
`frontend/src/lib/telemetry.ts:16` and `estimate.ts:5`: set `3: 970`. `print_settings.ts` validate default: `{ 2: 145, 3: 970, 4: 972 }`. `machine_calib.ts`: printhead far-end label `(970 mm)`.

- [ ] **Step 4: Run frontend + backend tests**

Run: `cd frontend && node --experimental-strip-types --test src/lib/telemetry.test.ts src/lib/elevation.test.ts` → PASS.
Run: `cd backend && uv run pytest tests/test_safety.py tests/test_print_settings.py -q` → PASS.
Run: `cd frontend && npm run build` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/vention_printer_interface frontend/src/lib
git commit -m "feat(travel): printhead soft-travel 840 -> 970 mm (measured end stop)"
```

---

## Task 2: Connect dedupe — show only reachable MachineMotion options

The connect `<select>` hardcodes both Ethernet (192.168.0.2) and USB (192.168.7.2); only the wired one is reachable, so the operator sees "two MMs" (spec §10). Build the options from `/api/discovery`, keeping only reachable machinemotion candidates (+ simulator + custom).

**Files:**
- Create: `frontend/src/lib/connect.ts`
- Test: `frontend/src/lib/connect.test.ts`
- Modify: `frontend/src/App.tsx` (connect `<select>`, ~line 116)

- [ ] **Step 1: Write the failing test**

`frontend/src/lib/connect.test.ts`:
```ts
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
```

- [ ] **Step 2: Run it, verify it fails**

Run: `cd frontend && node --experimental-strip-types --test src/lib/connect.test.ts`
Expected: FAIL ("does not provide an export named 'connectOptions'").

- [ ] **Step 3: Implement**

`frontend/src/lib/connect.ts`:
```ts
export interface Candidate { backend: string; ip: string | null; label: string; reachable: boolean }
export interface ConnectOption { value: string; label: string; ip: string | null }

/** Build connect-menu options: the simulator, each REACHABLE MachineMotion (so an unwired IP is
 *  never offered), then a custom-IP entry. `value` "usb"/"ethernet" carries the candidate label. */
export function connectOptions(cands: Candidate[]): ConnectOption[] {
  const out: ConnectOption[] = [];
  for (const c of cands) {
    if (c.backend === "simulated") out.push({ value: "simulated", label: "simulator", ip: null });
    else if (c.reachable) out.push({ value: c.label, label: `MachineMotion — ${c.label.toUpperCase()} ${c.ip}`, ip: c.ip });
  }
  out.push({ value: "custom", label: "MachineMotion — custom IP", ip: null });
  return out;
}
```

- [ ] **Step 4: Run test, verify pass**

Run: `cd frontend && node --experimental-strip-types --test src/lib/connect.test.ts` → PASS.

- [ ] **Step 5: Wire into App.tsx**

Add `import { connectOptions, type Candidate } from "./lib/connect.ts";`. Fetch discovery where the component already loads status (add a `useState<Candidate[]>` populated from `api.discovery()` on mount and when `showConnect` opens). Replace the hardcoded `<select>` options (App.tsx ~116) with:
```tsx
<select value={choice} onChange={(e) => setChoice(e.target.value)}>
  {connectOptions(candidates).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
</select>
```
Keep the existing `choice === "custom"` IP input and the `ip`/`reachable` logic. For a candidate value ("usb"/"ethernet") map to its ip in the existing `connect()` (it already maps usb→192.168.7.2, ethernet→192.168.0.2).

- [ ] **Step 6: Verify (browser) + build**

Run: `cd frontend && npm run build` → PASS. Start `uv run vpi-serve --backend simulated --port 8025`, open it, click the connection pill: the select shows **simulator + only the reachable MachineMotion + custom** (against the sim with no MM wired, just simulator + custom).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/connect.ts frontend/src/lib/connect.test.ts frontend/src/App.tsx
git commit -m "fix(connect): offer only reachable MachineMotion, kill the phantom IP"
```

---

## Task 3: Humanize the event log (axis numbers → names)

`EventLog.summary()` renders raw `axes=[4]`. Give events plain-language text with axis names (spec §9).

**Files:**
- Create: `frontend/src/lib/eventlog.ts`
- Test: `frontend/src/lib/eventlog.test.ts`
- Modify: `frontend/src/components/EventLog.tsx`

- [ ] **Step 1: Write the failing test**

`frontend/src/lib/eventlog.test.ts`:
```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { describeEvent } from "./eventlog.ts";

test("home names the axes", () => {
  assert.equal(describeEvent({ host_timestamp_ns: 0, label: "home", data: { axes: [4] } }),
    "Homed Recoater Gantry");
  assert.equal(describeEvent({ host_timestamp_ns: 0, label: "home", data: { axes: [3, 4] } }),
    "Homed Printhead Gantry, Recoater Gantry");
  assert.equal(describeEvent({ host_timestamp_ns: 0, label: "home", data: { axes: "all" } }),
    "Homed all axes");
});

test("move + heater + connect read naturally", () => {
  assert.equal(describeEvent({ host_timestamp_ns: 0, label: "heater_on", data: {} }), "Heater on");
  assert.equal(describeEvent({ host_timestamp_ns: 0, label: "connected", data: { backend: "machinemotion", ip: "192.168.7.2" } }),
    "Connected to MachineMotion (192.168.7.2)");
  assert.equal(describeEvent({ host_timestamp_ns: 0, label: "move", data: { axis: 1, applied_mm: 2.5 } }),
    "Moved Part Piston 2.5 mm");
});

test("unknown labels fall back to the raw summary", () => {
  assert.match(describeEvent({ host_timestamp_ns: 0, label: "custom_thing", data: { a: 1 } }), /custom_thing/);
});
```

- [ ] **Step 2: Run it, verify it fails**

Run: `cd frontend && node --experimental-strip-types --test src/lib/eventlog.test.ts`
Expected: FAIL (no export `describeEvent`).

- [ ] **Step 3: Implement**

`frontend/src/lib/eventlog.ts`:
```ts
import { AXIS_NAMES, type AxisNo, type EventItem } from "./telemetry.ts";

function axisName(a: unknown): string {
  return typeof a === "number" && (a as AxisNo) in AXIS_NAMES ? AXIS_NAMES[a as AxisNo] : `axis ${a}`;
}
function axisList(v: unknown): string {
  if (v === "all") return "all axes";
  if (Array.isArray(v)) return v.map(axisName).join(", ");
  return axisName(v);
}
function rawSummary(d: Record<string, unknown>): string {
  return Object.entries(d).filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => (typeof v === "object" ? `${k}=${JSON.stringify(v)}` : `${k}=${v}`)).join(" · ");
}

/** Plain-language one-liner for an event; falls back to key=value for labels we don't special-case. */
export function describeEvent(e: EventItem): string {
  const d = e.data as Record<string, unknown>;
  switch (e.label) {
    case "home": return `Homed ${axisList(d.axes)}`;
    case "move": return `Moved ${axisName(d.axis)} ${d.applied_mm} mm`;
    case "stop": return "Stopped all motion";
    case "heater_on": return "Heater on";
    case "heater_off": return "Heater off";
    case "armed": return "Took control (armed)";
    case "disarmed": return "Released control (read-only)";
    case "connected": return `Connected to ${d.backend === "simulated" ? "simulator" : "MachineMotion"}${d.ip ? ` (${d.ip})` : ""}`;
    case "disconnected": return "Disconnected";
    case "estop": return "Operator E-STOP — motion halted";
    case "estop_released": return "E-STOP released";
    case "fault_cleared": return "Fault cleared";
    case "fault": return `FAULT — ${Array.isArray(d.reasons) ? d.reasons.join("; ") : rawSummary(d)}`;
    default: return `${e.label}${Object.keys(d).length ? ` · ${rawSummary(d)}` : ""}`;
  }
}
```

- [ ] **Step 4: Run test, verify pass**

Run: `cd frontend && node --experimental-strip-types --test src/lib/eventlog.test.ts` → PASS.

- [ ] **Step 5: Wire into EventLog.tsx**

Replace the local `summary(e)` usage: import `describeEvent` and render `<td className="d">{describeEvent(e)}</td>`; delete the local `summary` function. Keep `fmtTime` and the warn-row regex.

- [ ] **Step 6: Verify + build**

Run: `cd frontend && node --experimental-strip-types --test src/lib && npm run build` → PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/eventlog.ts frontend/src/lib/eventlog.test.ts frontend/src/components/EventLog.tsx
git commit -m "feat(log): humanize the event log (axis names, plain language)"
```

---

## Task 4: Control — per-axis independent speed/accel

The current `Tuning` sets both axes in a module at once. Spec §5 requires each axis independent. Move speed/accel back to each `Axis`, kept compact (not the old sprawling disclosure).

**Files:**
- Modify: `frontend/src/components/views/ControlView.tsx`

- [ ] **Step 1: Remove the shared `Tuning`, give each `Axis` its own speed/accel**

In `ControlView.tsx`: delete the `Tuning` component and its two usages in the `gantries`/`pistons` modules. In `Axis`, add compact per-axis speed + accel controls under the axis header (before the jog row), reading current from `status.axis_motion[axis]` and cap from `limits`:
```tsx
const am = status?.axis_motion[String(a)];
const [speed, setSpeed] = useState(""); const [accel, setAccel] = useState("");
// ...inside the returned axis, after the pos row:
<div className="tune" style={{ display:"flex", gap:6, alignItems:"center", flexWrap:"wrap", margin:"6px 0" }}>
  <span className="lbl">spd</span>
  <input className="inp" type="number" style={{ width:64 }} value={speed} placeholder={String(am?.max_speed ?? "")} disabled={!ok} onChange={(e)=>setSpeed(e.target.value)} />
  <button className="small" disabled={!ok || speed===""} onClick={()=>call("set speed",()=>api.setAxisMotion(a,{max_speed:Number(speed)}).then(()=>setSpeed("")))}>set</button>
  <span className="cap">≤ {fmtSpeed(lim?.max_speed[String(a)])}</span>
  <span className="lbl" style={{ marginLeft:6 }}>acc</span>
  <input className="inp" type="number" style={{ width:64 }} value={accel} placeholder={String(am?.max_accel ?? "")} disabled={!ok} onChange={(e)=>setAccel(e.target.value)} />
  <button className="small" disabled={!ok || accel===""} onClick={()=>call("set accel",()=>api.setAxisMotion(a,{max_accel:Number(accel)}).then(()=>setAccel("")))}>set</button>
  <span className="cap">≤ {fmtAccel(lim?.max_accel[String(a)])}</span>
</div>
```
Re-add `const lim = status?.controller.limits;` in `Axis`. Update the module nodes to just `{stepper(...)}<Axis .../><Axis .../>` (no `Tuning`).

- [ ] **Step 2: Verify (browser) + build**

Run: `cd frontend && npm run build` → PASS (tsc clean). Against `--backend simulated`, take control → Control: each of the 4 axes shows its **own** spd/acc inputs; setting Printhead speed does not change Recoater's placeholder.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/views/ControlView.tsx
git commit -m "feat(control): independent per-axis speed & acceleration"
```

---

## Task 5: Control — remove Load Cart / Clear Bed, per-gantry homing only

Spec §5: drop the park macros from the UI; home one gantry at a time (no "home all").

**Files:**
- Modify: `frontend/src/components/views/ControlView.tsx` (the `motion` module)

- [ ] **Step 1: Rework the `motion` module**

Replace the `motion` module node's contents: remove the **LOAD CART** and **CLEAR BED** buttons and the load-cart hint. Replace the single **HOME GANTRIES** button with two per-gantry buttons, each confirmed:
```tsx
<div className="actions" style={{ marginTop:0 }}>
  <button className="cta" disabled={!ok} onClick={()=>{ if(window.confirm("Home the printhead gantry?")) call("home printhead",()=>api.home([3])); }}>HOME PRINTHEAD</button>
  <button className="cta" disabled={!ok} onClick={()=>{ if(window.confirm("Home the recoater gantry?")) call("home recoater",()=>api.home([4])); }}>HOME RECOATER</button>
  <button className="cta danger" disabled={!gates.connected} onClick={()=>call("stop",api.stop)}>STOP</button>
</div>
<div className="hint" style={{ marginTop:10 }}>Home one gantry at a time. Pistons are never auto-homed — homing a piston ejects powder.</div>
```
Leave the per-axis home `⌂` on the piston axes (with the existing powder-eject confirm) untouched. `api.macro` may remain in `api.ts` for now (unused); the backend macros are untouched.

- [ ] **Step 2: Verify (browser) + build**

Run: `cd frontend && npm run build` → PASS. Control page: no Load Cart / Clear Bed; two per-gantry home buttons, each prompting a confirm; STOP present.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/views/ControlView.tsx
git commit -m "feat(control): remove load-cart/clear-bed, home gantries one at a time"
```

---

## Task 6: Wire in the real machine wireframe

`MachineImage` already overlays live markers on `public/machine/printer.png` and falls back to the schematic when it's absent (memory + `MachineImage.tsx`). Drop the real sketch in and calibrate.

**Files:**
- Create: `frontend/public/machine/printer.png` (copied asset)
- Modify: `frontend/public/machine/calibration.json` (after calibrating)

- [ ] **Step 1: Copy the sketch into place**

```bash
cp "/Users/mattmccoy/GaTech Dropbox/Matthew McCoy/mattmccoy-research/research/dissertation_materials/proposal/writing/figures/machine_sketch_bw.png" "frontend/public/machine/printer.png"
```

- [ ] **Step 2: Rebuild so the asset ships**

Run: `cd frontend && npm run build` → PASS; confirm `dist/machine/printer.png` exists (`ls frontend/dist/machine`).

- [ ] **Step 3: Verify + calibrate (browser)**

Serve, open the machine module: the wireframe now shows the real sketch instead of the schematic. Use the module's "calibrate markers" flow (8 clicks: printhead 0 & far, recoater 0 & far, feed/build piston top & bottom) and paste the emitted JSON into `frontend/public/machine/calibration.json`. Confirm the live markers track the rails/pistons on the sketch.

- [ ] **Step 4: Commit**

```bash
git add frontend/public/machine/printer.png frontend/public/machine/calibration.json
git commit -m "feat(machine): wire in the real printer wireframe + calibrate"
```

---

## Self-review notes

- Spec coverage: §5 (Control cleanup, per-axis speed/accel, per-gantry homing, remove park macros → Tasks 4,5), §10 (printhead 970 → Task 1, connect dedupe → Task 2, wireframe → Task 6), §9 (humanized log → Task 3). Readability (§10) was already applied to the mockup and is folded into these components' styles; a broader type/contrast pass across the real app is deferred to a later polish plan.
- Not in this plan (own plans): priming rebuild (Plan 2), print routine + IPA model (Plan 3), digital preview (Plan 4), GH Pages + e-stop reset + Job/Runs (Plan 5).
- Types: `connectOptions`/`Candidate`/`ConnectOption`, `describeEvent` are used consistently between their tasks and their wiring.
