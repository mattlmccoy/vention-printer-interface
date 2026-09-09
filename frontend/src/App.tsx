import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { api, operatorBase, setOperatorBase } from "./lib/api.ts";
import { formatError, gates as computeGates } from "./lib/format.ts";
import { PLOT_WINDOWS, layoutReducer, loadLayout, saveLayout, type Section } from "./lib/layout.ts";
import { checkHandshake, saveOperatorBase, UI_API_VERSION, wsUrl } from "./lib/operator.ts";
import { AXES, TraceBuffer, type AxisNo, type StatusPayload } from "./lib/telemetry.ts";
import { compileRecipe, type RecipePlan } from "./lib/recipe.ts";
import { StudioFrame } from "./components/studio/StudioFrame.tsx";
import { ToolStrip } from "./components/studio/ToolStrip.tsx";
import { Rail } from "./components/studio/Rail.tsx";
import { RailSection } from "./components/studio/RailSection.tsx";
import { PlotDock } from "./components/studio/PlotDock.tsx";
import { StatusBar } from "./components/studio/StatusBar.tsx";
import { MachineView } from "./components/MachineView.tsx";
import { TimePlot } from "./components/TimePlot.tsx";
import { ErrorBoundary } from "./components/ErrorBoundary.tsx";
import { ArmSection, AxesSection, ConnectionSection, HeaterSection, RecipeSection, RecordingSection } from "./components/Sections.tsx";

const storage = typeof localStorage === "undefined" ? null : localStorage;

export function App() {
  const [layout, dispatch] = useReducer(layoutReducer, null, () => loadLayout(storage));
  useEffect(() => saveLayout(storage, layout), [layout]);
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [reachable, setReachable] = useState(false);
  const [base, setBase] = useState(operatorBase());
  const [baseInput, setBaseInput] = useState(operatorBase());
  const [err, setErr] = useState<string | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  const [handshake, setHandshake] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const traces = useRef<Record<AxisNo, TraceBuffer>>({ 1: new TraceBuffer(36000), 2: new TraceBuffer(36000), 3: new TraceBuffer(36000), 4: new TraceBuffer(36000) });
  const samples = useRef<number[]>([]);

  // Live status over the WebSocket, reconnecting every second while the operator is down.
  useEffect(() => {
    let ws: WebSocket | null = null; let alive = true; let timer: number | undefined;
    const open = () => {
      if (!alive) return;
      ws = new WebSocket(wsUrl(base, "/ws/telemetry"));
      ws.onopen = () => { setReachable(true); api.health().then((h) => { setVersion(h.version); const hs = checkHandshake(UI_API_VERSION, h.api_version); setHandshake(hs.level === "ok" ? null : hs.message); }).catch(() => undefined); };
      ws.onmessage = (ev) => {
        if (typeof ev.data !== "string") return;
        const s = JSON.parse(ev.data) as StatusPayload;
        setStatus(s);
        const tel = s.controller.telemetry;
        if (tel) {
          const t = tel.host_timestamp_ns / 1e9;
          const last = samples.current[samples.current.length - 1];
          if (last !== t) {
            samples.current.push(t); if (samples.current.length > 50) samples.current.shift();
            for (const a of AXES) { const v = tel.positions[String(a)]; if (typeof v === "number") traces.current[a].push(t, v); }
            setTick((n) => n + 1);
          }
        }
      };
      ws.onclose = () => { setReachable(false); if (alive) timer = window.setTimeout(open, 1000); };
      ws.onerror = () => ws?.close();
    };
    open();
    return () => { alive = false; if (timer) clearTimeout(timer); ws?.close(); };
  }, [base]);

  const call = useCallback(async (label: string, fn: () => Promise<unknown>) => {
    try { await fn(); setErr(null); } catch (e) { setErr(`${label}: ${formatError(e)}`); }
  }, []);
  const applyBase = () => { saveOperatorBase(storage, baseInput); setOperatorBase(baseInput.trim().replace(/\/+$/, "")); setBase(operatorBase()); };
  const g = computeGates(status, reachable);
  const n = samples.current.length;
  const pollHz = n > 2 ? (n - 1) / (samples.current[n - 1] - samples.current[0]) : null;
  const sec = (id: Section, title: string, tag?: string, tagWarn?: boolean) => ({ id, title, open: layout.sections[id], onToggle: () => dispatch({ type: "toggleSection", section: id }), tag, tagWarn });
  const onTool = (t: typeof layout.tool) => { dispatch({ type: "setTool", tool: t }); if (t === "home") dispatch({ type: "openSection", section: "axes" }); if (t === "recipe") dispatch({ type: "openSection", section: "recipe" }); };
  const c = status?.controller;
  const r = status?.recipe;
  const curStep = r?.current_step && r.plan ? compileRecipe(r.plan as unknown as RecipePlan)[r.current_step.index] ?? null : null;
  const collapsed = !layout.rail && !layout.dock;
  const dotCls = !reachable ? "err" : g.faulted ? "err" : g.connected ? "live" : "warn";

  const topbar = (
    <>
      <span className="wordmark">VENTION PRINTER INTERFACE</span>
      <span className="row"><span className={`dot ${dotCls}`} /> <span className="muted">{!reachable ? "operator unreachable" : c?.state ?? "—"}{g.armed ? " · ARMED" : ""}</span></span>
      {handshake && <span className="badge warn">{handshake}</span>}
      <span className="spacer" />
      {err && <span className="badge bad" title={err}>{err.length > 90 ? err.slice(0, 90) + "…" : err}</span>}
      {g.faulted && <span className="badge bad">FAULT — {c?.fault_reasons.join("; ")}</span>}
    </>
  );
  const common = { status, gates: g, call };
  return (
    <ErrorBoundary>
      <StudioFrame layout={layout} dispatch={dispatch} topbar={topbar}
        strip={<ToolStrip tool={layout.tool} onTool={onTool} collapsed={collapsed} onCollapseAll={() => dispatch({ type: collapsed ? "restoreAll" : "collapseAll" })} />}
        center={<MachineView status={status} jog={layout.tool === "jog" && g.controllable} currentStep={curStep} onJog={(axis, mm) => call(`jog ${axis}`, () => api.move(axis, "abs", mm))} />}
        dock={<PlotDock onCollapse={() => dispatch({ type: "toggle", panel: "dock" })} controls={<select value={layout.plotWindowS} onChange={(e) => dispatch({ type: "setPlotWindow", s: Number(e.target.value) })}>{PLOT_WINDOWS.map((w) => <option key={w} value={w}>{w >= 60 ? `${w / 60} min` : `${w} s`}</option>)}</select>}>
          <TimePlot traces={traces.current} windowS={layout.plotWindowS} tick={tick} />
        </PlotDock>}
        rail={<Rail>
          <RailSection {...sec("connection", "connection", c?.backend === "none" || !c ? "idle" : c.backend)}><ConnectionSection {...common} baseInput={baseInput} setBaseInput={setBaseInput} applyBase={applyBase} version={version} /></RailSection>
          <RailSection {...sec("arm", "arm / e-stop", g.faulted ? "FAULT" : g.armed ? "armed" : g.connected ? "read-only" : undefined, g.faulted)}><ArmSection {...common} /></RailSection>
          <RailSection {...sec("axes", "axes")}><AxesSection {...common} /></RailSection>
          <RailSection {...sec("heater", "heater", c?.heater.on ? "ON" : undefined, !!c?.heater.on)}><HeaterSection {...common} /></RailSection>
          <RailSection {...sec("recipe", "recipe", r && r.state !== "idle" ? r.state : undefined, r?.state === "fault")}><RecipeSection {...common} /></RailSection>
          <RailSection {...sec("recording", "recording", status?.recording.active ? "REC" : undefined)}><RecordingSection {...common} /></RailSection>
        </Rail>}
        statusbar={<StatusBar state={c?.state ?? "disconnected"} backend={c?.backend ?? "none"} pollHz={pollHz} reachable={reachable}
          estop={c?.telemetry?.estop_triggered ?? null} drivesReady={c?.telemetry?.drives_ready ?? null} heaterOn={c?.heater.on ?? null} heaterOnS={c?.heater.on_s ?? 0} heaterMaxS={c?.heater.max_on_s ?? 0}
          recActive={status?.recording.active ?? false} recRun={status?.recording.run ?? null} recipeState={r?.state ?? "idle"} version={version} apiWarning={null} />}
      />
    </ErrorBoundary>
  );
}
