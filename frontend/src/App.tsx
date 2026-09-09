import { useCallback, useEffect, useRef, useState } from "react";
import { api, operatorBase, setOperatorBase, SITE_MODE } from "./lib/api.ts";
import { formatError, gates as computeGates } from "./lib/format.ts";
import { checkHandshake, saveOperatorBase, UI_API_VERSION, wsUrl } from "./lib/operator.ts";
import { loadConsole, saveConsole, VIEWS, type View } from "./lib/console.ts";
import type { StatusPayload } from "./lib/telemetry.ts";
import { ErrorBoundary } from "./components/ErrorBoundary.tsx";
import { StatusBar } from "./components/StatusBar.tsx";
import { PrintView } from "./components/views/PrintView.tsx";
import { PrepareView } from "./components/views/PrepareView.tsx";
import { ControlView } from "./components/views/ControlView.tsx";
import { RunsView } from "./components/views/RunsView.tsx";

const storage = typeof localStorage === "undefined" ? null : localStorage;

export function App() {
  const [ui, setUi] = useState(() => loadConsole(storage));
  useEffect(() => saveConsole(storage, ui), [ui]);
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [reachable, setReachable] = useState(false);
  const [base, setBase] = useState(operatorBase());
  const [baseInput, setBaseInput] = useState(operatorBase());
  const [err, setErr] = useState<string | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  const [handshake, setHandshake] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showConnect, setShowConnect] = useState(false);
  const [choice, setChoice] = useState("simulated");
  const [ip, setIp] = useState("192.168.0.2");
  const [heaterIo, setHeaterIo] = useState("1,0");
  const samples = useRef<number[]>([]);

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
        const t = s.controller.telemetry?.host_timestamp_ns;
        if (t && samples.current[samples.current.length - 1] !== t) { samples.current.push(t); if (samples.current.length > 50) samples.current.shift(); }
      };
      ws.onclose = () => { setReachable(false); if (alive) timer = window.setTimeout(open, 1000); };
      ws.onerror = () => ws?.close();
    };
    open();
    return () => { alive = false; if (timer) clearTimeout(timer); ws?.close(); };
  }, [base]);

  const call = useCallback(async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    try { await fn(); setErr(null); } catch (e) { setErr(`${label}: ${formatError(e)}`); } finally { setBusy(null); }
  }, []);
  const g = computeGates(status, reachable);
  const n = samples.current.length;
  const pollHz = n > 2 ? ((n - 1) * 1e9) / (samples.current[n - 1] - samples.current[0]) : null;
  const c = status?.controller;
  const r = status?.recipe;
  const setView = (view: View) => setUi((u) => ({ ...u, view }));
  const applyBase = () => { saveOperatorBase(storage, baseInput); setOperatorBase(baseInput.trim().replace(/\/+$/, "")); setBase(operatorBase()); };
  const [dev, pin] = heaterIo.split(",").map((s) => parseInt(s.trim(), 10));
  const heaterOk = Number.isInteger(dev) && Number.isInteger(pin) && dev >= 1 && dev <= 8 && pin >= 0 && pin <= 3;
  const connect = () => call("connect", () => api.connect({ backend: choice === "simulated" ? "simulated" : "machinemotion", ip: choice === "ethernet" ? "192.168.0.2" : choice === "usb" ? "192.168.7.2" : choice === "custom" ? ip : null, heater_io: [dev, pin] }).then(() => setShowConnect(false)));
  const dotCls = !reachable ? "err" : g.faulted ? "err" : g.connected ? "live" : "warn";
  const ctrlLabel = !reachable ? "operator unreachable" : !g.connected ? "connect" : c?.backend === "simulated" ? "simulator" : `MachineMotion ${String((status?.device as { version?: string })?.version ?? "")}`;
  const estopStillAsserted = c?.telemetry?.estop_triggered !== false;

  return (
    <ErrorBoundary>
      <div className="console">
        <header className="top">
          <span className="wordmark">BINDER JET CONSOLE</span>
          <nav className="tabs">{VIEWS.map((v) => <button key={v} className={ui.view === v ? "active" : ""} onClick={() => setView(v)}>{v}</button>)}</nav>
          <button className="pill" onClick={() => setShowConnect((s) => !s)} title="connection"><span className={`dot ${dotCls}`} />{ctrlLabel}</button>
          {handshake && <span className="pill warn">{handshake}</span>}
          <span className="spacer" />
          {busy && <span className="muted mono">{busy}…</span>}
          <button className={`arm ${g.armed ? "on" : ""}`} disabled={!g.connected || g.faulted} onClick={() => call(g.armed ? "disarm" : "arm", g.armed ? api.disarm : api.arm)} title={g.armed ? "Disarm: drop control, heater off" : "Arm: take control of the machine"}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="4" y="10" width="16" height="11" rx="2" /><path d={g.armed ? "M8 10V7a4 4 0 0 1 8 0" : "M8 10V7a4 4 0 0 1 8 0v3"} /></svg>
            {g.armed ? "ARMED" : g.faulted ? "FAULTED" : g.connected ? "ARM" : "ARM"}
          </button>
          <button className="estop" disabled={!g.connected} onClick={() => call("e-stop", api.estop)}>■ E-STOP</button>
        </header>
        <div>
          {g.faulted && (
            <div className="banner err">
              <b>FAULT</b><span>{c?.fault_reasons.join("; ")}</span>
              <span className="step"><span className="n">1</span>{estopStillAsserted ? <button onClick={() => call("release e-stop", api.estopRelease)}>release e-stop + reset drives</button> : <span>e-stop released</span>}</span>
              <span className="step"><span className="n">2</span><button onClick={() => call("clear fault", api.clearFault)}>clear fault</button></span>
              <span className="step"><span className="n">3</span><span>then ARM again</span></span>
              {err && <span className="apierr">{err}</span>}
            </div>
          )}
          {!g.faulted && (err || (c && c.warnings.length > 0)) && <div className={`banner ${err ? "err" : "warn"}`}>{err ? <span className="apierr" style={{ marginLeft: 0, maxWidth: "100%" }}>{err}</span> : c?.warnings.join("; ")}{err && <button style={{ marginLeft: "auto" }} onClick={() => setErr(null)}>dismiss</button>}</div>}
          {showConnect && (
            <div className="banner">
              {g.connected ? <button onClick={() => call("disconnect", () => api.disconnect().then(() => setShowConnect(false)))}>disconnect</button> : <>
                <select value={choice} onChange={(e) => setChoice(e.target.value)}><option value="simulated">simulator</option><option value="ethernet">MachineMotion — Ethernet 192.168.0.2</option><option value="usb">MachineMotion — USB 192.168.7.2</option><option value="custom">MachineMotion — custom IP</option></select>
                {choice === "custom" && <input type="text" value={ip} onChange={(e) => setIp(e.target.value)} />}
                <label className="hint">heater io <input type="text" value={heaterIo} onChange={(e) => setHeaterIo(e.target.value)} style={{ width: 52 }} title="IO module id,pin — unverified until commissioning" /></label>
                <button disabled={!reachable || !heaterOk} onClick={connect}>connect (read-only)</button>
                <span className="hint">Connecting is read-only. Check positions against the machine, then ARM.</span>
              </>}
              {SITE_MODE && <label className="hint" style={{ marginLeft: "auto" }}>operator <input type="text" value={baseInput} onChange={(e) => setBaseInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") applyBase(); }} /> <button onClick={applyBase}>apply</button></label>}
            </div>
          )}
        </div>
        {ui.view === "print" && <PrintView status={status} gates={g} call={call} onPrepare={() => setView("prepare")} />}
        {ui.view === "prepare" && <PrepareView status={status} gates={g} call={call} onStarted={() => setView("print")} />}
        {ui.view === "control" && <ControlView status={status} gates={g} call={call} gantryStep={ui.gantryStep} pistonStep={ui.pistonStep} setGantryStep={(s) => setUi((u) => ({ ...u, gantryStep: s }))} setPistonStep={(s) => setUi((u) => ({ ...u, pistonStep: s }))} />}
        {ui.view === "runs" && <RunsView status={status} gates={g} call={call} />}
        <StatusBar state={c?.state ?? "disconnected"} backend={c?.backend ?? "none"} pollHz={pollHz} reachable={reachable}
          estop={c?.telemetry?.estop_triggered ?? null} drivesReady={c?.telemetry?.drives_ready ?? null} heaterOn={c?.heater.on ?? null} heaterOnS={c?.heater.on_s ?? 0} heaterMaxS={c?.heater.max_on_s ?? 0}
          recActive={status?.recording.active ?? false} recRun={status?.recording.run ?? null} recipeState={r?.state ?? "idle"} version={version} />
      </div>
    </ErrorBoundary>
  );
}
