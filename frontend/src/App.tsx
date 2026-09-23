import { useCallback, useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { api, operatorBase, setOperatorBase, SITE_MODE, type VisionStatus } from "./lib/api.ts";
import { formatError, gates as computeGates } from "./lib/format.ts";
import { checkHandshake, saveOperatorBase, UI_API_VERSION, wsUrl } from "./lib/operator.ts";
import { loadConsole, saveConsole, type View } from "./lib/console.ts";
import { connectOptions, type Candidate } from "./lib/connect.ts";
import { dismissQuickStart, shouldShowQuickStart } from "./lib/vision.ts";
import type { StatusPayload } from "./lib/telemetry.ts";
import { ErrorBoundary } from "./components/ErrorBoundary.tsx";
import { StatusBar } from "./components/StatusBar.tsx";
import { MachineDock } from "./components/MachineDock.tsx";
import { ScienceCaptureClient } from "./components/ScienceCaptureClient.tsx";
import { OverviewTimelapseClient } from "./components/OverviewTimelapseClient.tsx";
import { CameraStudio } from "./components/CameraStudio.tsx";
import { QuickStartVision } from "./components/QuickStartVision.tsx";
import { PrintView } from "./components/views/PrintView.tsx";
import { JobView } from "./components/views/JobView.tsx";
import { ControlView } from "./components/views/ControlView.tsx";
import { PrimingView } from "./components/views/PrimingView.tsx";
import { RunsView } from "./components/views/RunsView.tsx";
import { SettingsView } from "./components/views/SettingsView.tsx";
import { AnalysisView } from "./components/views/AnalysisView.tsx";

const storage = typeof localStorage === "undefined" ? null : localStorage;

const INSTALL_SH = "curl -fsSL https://raw.githubusercontent.com/mattlmccoy/vention-printer-interface/main/install.sh | bash";
const INSTALL_PS = "irm https://raw.githubusercontent.com/mattlmccoy/vention-printer-interface/main/install.ps1 | iex";

export function App() {
  const [ui, setUi] = useState(() => loadConsole(storage));
  useEffect(() => saveConsole(storage, ui), [ui]);
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [reachable, setReachable] = useState(false);
  const [base, setBase] = useState(operatorBase());
  const [baseInput, setBaseInput] = useState(operatorBase());
  const [err, setErr] = useState<string | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  const [opBuild, setOpBuild] = useState<string | null>(null); // operator's git commit (health.build)
  const [handshake, setHandshake] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [wsFails, setWsFails] = useState(0);
  const [copied, setCopied] = useState(false);
  const [showConnect, setShowConnect] = useState(false);
  const [choice, setChoice] = useState("simulated");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [ip, setIp] = useState("192.168.0.2");
  const [heaterIo, setHeaterIo] = useState("1,0");
  const samples = useRef<number[]>([]);
  const [visionStatus, setVisionStatus] = useState<VisionStatus | null>(null);
  const [quickStartOpen, setQuickStartOpen] = useState(false); // explicit re-open, e.g. from Settings
  const [cameraStudio, setCameraStudio] = useState(false); // both-cameras studio modal (#12)
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    const q = typeof location !== "undefined" ? new URLSearchParams(location.search).get("theme") : null;
    if (q === "light" || q === "dark") return q;
    return storage?.getItem("vpi.theme") === "light" ? "light" : "dark";
  });

  // Theme: dark is the default (bare :root); "light" stamps data-theme on <html> to swap tokens.
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { storage?.setItem("vpi.theme", theme); } catch { /* ignore */ }
  }, [theme]);

  // Persistent machine dock (right side): width + open state, remembered locally.
  const [dock, setDock] = useState<{ w: number; open: boolean }>(() => {
    try { const j = JSON.parse(storage?.getItem("vpi.dock") ?? "") as { w?: number; open?: boolean }; if (j && typeof j.w === "number") return { w: j.w, open: j.open !== false }; } catch { /* ignore */ }
    return { w: 380, open: true };
  });
  useEffect(() => { try { storage?.setItem("vpi.dock", JSON.stringify(dock)); } catch { /* ignore */ } }, [dock]);

  // Deep-link the active view via URL hash (#control, #print, …) — also lets tooling target a page.
  useEffect(() => {
    const names = ["control", "job", "priming", "print", "runs", "analysis", "cameras", "settings"];
    const apply = () => { const h = location.hash.slice(1); if (names.includes(h)) setUi((u) => (u.view === h ? u : { ...u, view: h as View })); };
    apply();
    window.addEventListener("hashchange", apply);
    return () => window.removeEventListener("hashchange", apply);
  }, []);
  const dockDrag = (e: ReactPointerEvent) => {
    e.preventDefault();
    const startX = e.clientX; const startW = dock.w;
    const move = (ev: PointerEvent) => { const w = Math.max(262, Math.min(560, startW + (startX - ev.clientX))); setDock((d) => ({ ...d, w })); };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up);
      setDock((d) => { const SNAP = [320, 380, 440, 520]; const w = SNAP.reduce((a, b) => (Math.abs(b - d.w) < Math.abs(a - d.w) ? b : a)); return { ...d, w }; }); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  };

  // Camera auto-connect + quick-start (A7): poll /api/vision/status while the operator is
  // reachable so shouldShowQuickStart can gate the first-run/re-assign wizard on roles_resolved.
  useEffect(() => {
    if (!reachable) return;
    let live = true;
    const poll = () => api.visionStatus().then((s) => { if (live) setVisionStatus(s); }).catch(() => undefined);
    poll();
    const id = window.setInterval(poll, 5000);
    return () => { live = false; window.clearInterval(id); };
  }, [reachable, base]);

  useEffect(() => {
    let ws: WebSocket | null = null; let alive = true; let timer: number | undefined;
    const open = () => {
      if (!alive) return;
      ws = new WebSocket(wsUrl(base, "/ws/telemetry"));
      ws.onopen = () => { setReachable(true); setWsFails(0); api.health().then((h) => { setVersion(h.version); setOpBuild(h.build ?? null); const hs = checkHandshake(UI_API_VERSION, h.api_version); setHandshake(hs.level === "ok" ? null : hs.message); }).catch(() => undefined); };
      ws.onmessage = (ev) => {
        if (typeof ev.data !== "string") return;
        const s = JSON.parse(ev.data) as StatusPayload;
        setStatus(s);
        const t = s.controller.telemetry?.host_timestamp_ns;
        if (t && samples.current[samples.current.length - 1] !== t) { samples.current.push(t); if (samples.current.length > 50) samples.current.shift(); }
      };
      ws.onclose = () => { setReachable(false); setWsFails((f) => Math.min(f + 1, 99)); if (alive) timer = window.setTimeout(open, 1000); };
      ws.onerror = () => ws?.close();
    };
    open();
    return () => { alive = false; if (timer) clearTimeout(timer); ws?.close(); };
  }, [base]);

  useEffect(() => {
    if (!showConnect) return;
    api.discovery().then((d) => setCandidates(d.candidates as Candidate[])).catch(() => undefined);
  }, [showConnect, base]);

  const copyInstall = () => { navigator.clipboard?.writeText(INSTALL_SH).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1500); }).catch(() => undefined); };
  // In site mode (the hosted UI), show the "how to start the operator" help once the local operator
  // has failed to answer a couple of reconnect attempts (~2s) — driven by the WS reconnect loop, not
  // a standalone timer, so it reveals reliably. Hidden the moment the operator connects (wsFails→0).
  const showHelp = SITE_MODE && !reachable && wsFails >= 2;

  const call = useCallback(async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    try { await fn(); setErr(null); } catch (e) { setErr(`${label}: ${formatError(e)}`); } finally { setBusy(null); }
  }, []);
  const g = computeGates(status, reachable);
  const noWizard = typeof location !== "undefined" && new URLSearchParams(location.search).has("nowizard");
  const showQuickStart = !noWizard && (quickStartOpen || shouldShowQuickStart(visionStatus, storage));
  const n = samples.current.length;
  const pollHz = n > 2 ? ((n - 1) * 1e9) / (samples.current[n - 1] - samples.current[0]) : null;
  const c = status?.controller;
  const r = status?.print;
  const setView = (view: View) => setUi((u) => ({ ...u, view }));
  const applyBase = () => { saveOperatorBase(storage, baseInput); setOperatorBase(baseInput.trim().replace(/\/+$/, "")); setBase(operatorBase()); };
  const [dev, pin] = heaterIo.split(",").map((s) => parseInt(s.trim(), 10));
  const heaterOk = Number.isInteger(dev) && Number.isInteger(pin) && dev >= 1 && dev <= 8 && pin >= 0 && pin <= 3;
  // Connecting takes control unless "read-only" is ticked (commissioning, or someone else has the machine).
  const connect = () => call("connect", async () => {
    await api.connect({ backend: choice === "simulated" ? "simulated" : "machinemotion", ip: choice === "ethernet" ? "192.168.0.2" : choice === "usb" ? "192.168.7.2" : choice === "custom" ? ip : null, heater_io: [dev, pin] });
    if (!ui.readOnlyConnect) { await new Promise((res) => setTimeout(res, 400)); await api.arm(); }
    setShowConnect(false);
  });
  const clearFault = () => call("clear fault", async () => { await api.clearFault(); if (!ui.readOnlyConnect) await api.arm(); });
  const dotCls = !reachable ? "err" : g.faulted ? "err" : g.armed ? "live" : g.connected ? "warn" : "warn";
  const pillLabel = !reachable ? "operator unreachable" : !g.connected ? "connect" : `${c?.backend === "simulated" ? "simulator" : "MachineMotion"}${g.armed ? "" : g.faulted ? " · faulted" : " · read-only"}`;
  // drives_ready is only true after the physical E-STOP is released + the machine reset by hand, so
  // it proves the E-STOP is clear and dominates a stale/lingering estop_triggered flag (matches the
  // backend printer.read_telemetry invariant). Without this the recovery gets stuck on step 1.
  const estopStillAsserted = c?.telemetry?.drives_ready !== true && c?.telemetry?.estop_triggered !== false;
  // Incremental drives read ~0 after a power-cycle until homed. If any axis is unreferenced the
  // diagram's positions are not true position — warn globally and point at homing (Control tab).
  const refMap = c?.telemetry?.referenced;
  const anyUnref = !!refMap && Object.values(refMap).some((v) => v === false);

  return (
    <ErrorBoundary>
      <div className="console">
        <header className="top">
          <span className="wordmark">VENTION PRINTER INTERFACE<span className="sub">MachineMotion 2</span></span>
          <nav className="tabs">
            <div className="tabgroup build">
              <span className="tglabel">BUILD</span>
              {(["job", "priming", "print"] as View[]).map((v) => <button key={v} className={`bt${ui.view === v ? " active" : ""}`} onClick={() => setView(v)}>{v}</button>)}
            </div>
            <div className="tabgroup">
              {(["control", "runs", "analysis", "settings"] as View[]).map((v) => <button key={v} className={`bt${ui.view === v || (v === "settings" && ui.view === "cameras") ? " active" : ""}`} onClick={() => setView(v)}>{v}</button>)}
            </div>
          </nav>
          <button className={`pill${g.faulted ? " err" : ""}`} onClick={() => setShowConnect((s) => !s)} title="connection">
            <span className={`dot ${dotCls}`} />{pillLabel}
            {g.connected && !g.armed && !g.faulted && <svg className="lock" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>}
          </button>
          {handshake && <span className="pill warn">{handshake}</span>}
          <span className="spacer" />
          {busy && <span className="muted mono">{busy}…</span>}
          <button className="iconbtn" onClick={() => setCameraStudio(true)} title="Camera studio — both cameras, snapshots & recording" aria-label="open camera studio">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" /><circle cx="12" cy="13" r="4" /></svg>
          </button>
          <button className={`iconbtn${dock.open ? " on" : ""}`} onClick={() => setDock((d) => ({ ...d, open: !d.open }))} title="Toggle machine dock" aria-label="toggle machine dock" aria-pressed={dock.open}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="4" width="18" height="16" rx="2" /><line x1="15" y1="4" x2="15" y2="20" /></svg>
          </button>
          <button className="iconbtn" onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))} title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} aria-label="toggle theme">
            {theme === "dark"
              ? <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
              : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>}
          </button>
          <button className="iconbtn" title="Restart the operator (backend) — refused while a print is running. The page will reconnect on its own after a few seconds." aria-label="restart operator"
            onClick={() => { if (window.confirm("Restart the operator process?\n\nThis relaunches the backend server. It is refused while a print is running. The machine keeps power; after it comes back, reconnect and REFERENCE AT CURRENT if positions read unreferenced.")) call("restart operator", api.operatorRestart); }}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v5h-5" /></svg>
          </button>
          <button className="estop" disabled={!g.connected} onClick={() => call("e-stop", api.estop)}>■ E-STOP</button>
        </header>
        <div>
          {g.faulted && (
            <div className="banner err recovery">
              <b>FAULT</b>
              <span className="reason" title={c?.fault_reasons.join("; ")}>{c?.fault_reasons.join("; ")}</span>
              <span className={`rstep${estopStillAsserted ? "" : " done"}`}
                title="An E-STOP can only be released by hand at the machine (ISO 13850). Software cannot release it.">
                <span className="n">1</span>{estopStillAsserted ? <>release <b>E-STOP</b> by hand</> : <>E-STOP released</>}
              </span>
              <span className={`rstep${c?.telemetry?.drives_ready === true ? " done" : ""}`}>
                <span className="n">2</span>{c?.telemetry?.drives_ready === true
                  ? <>drives ready</>
                  : estopStillAsserted
                    ? <span className="muted">reset drives</span>
                    : <button className="small" onClick={() => call("reset drives", api.estopResetDrives)}>reset drives</button>}
              </span>
              <span className="rstep">
                <span className="n">3</span><button className="small" onClick={clearFault} disabled={estopStillAsserted || c?.telemetry?.drives_ready !== true}>clear fault{ui.readOnlyConnect ? "" : " + take control"}</button>
              </span>
              {err && <span className="apierr" title={err}>{err}</span>}
            </div>
          )}
          {!g.faulted && (err || (c && c.warnings.length > 0)) && <div className={`banner ${err ? "err" : "warn"}`}>{err ? <span className="apierr" style={{ marginLeft: 0, maxWidth: "100%" }}>{err}</span> : c?.warnings.join("; ")}{err && <button style={{ marginLeft: "auto" }} onClick={() => setErr(null)}>dismiss</button>}</div>}
          {!g.faulted && g.connected && anyUnref && (
            <div className="banner warn">
              <b>NOT HOMED</b>
              <span className="reason">positions are unreferenced since power-on — the machine may not be where the diagram shows. Home the axes to reference them.</span>
              {ui.view !== "control" && <button className="small" style={{ marginLeft: "auto" }} onClick={() => setView("control")}>go to Control</button>}
            </div>
          )}
          {showConnect && (
            <div className="banner">
              {g.connected ? <>
                {!g.armed && !g.faulted && <button onClick={() => call("take control", api.arm)}>take control</button>}
                {g.armed && <button onClick={() => call("release control", api.disarm)}>release control (read-only)</button>}
                <button onClick={() => call("disconnect", () => api.disconnect().then(() => setShowConnect(false)))}>disconnect</button>
              </> : <>
                <select value={choice} onChange={(e) => setChoice(e.target.value)}>{connectOptions(candidates).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
                {choice === "custom" && <input type="text" value={ip} onChange={(e) => setIp(e.target.value)} />}
                <label className="hint">heater io <input type="text" value={heaterIo} onChange={(e) => setHeaterIo(e.target.value)} style={{ width: 56 }} title="IO module id,pin — unverified until commissioning" /></label>
                <label className="hint"><input type="checkbox" checked={ui.readOnlyConnect} onChange={(e) => setUi((u) => ({ ...u, readOnlyConnect: e.target.checked }))} /> read-only (watch only)</label>
                <button disabled={!reachable || !heaterOk} onClick={connect}>{ui.readOnlyConnect ? "connect" : "connect and take control"}</button>
              </>}
              {SITE_MODE && <label className="hint" style={{ marginLeft: "auto" }}>operator <input type="text" value={baseInput} onChange={(e) => setBaseInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") applyBase(); }} /> <button onClick={applyBase}>apply</button></label>}
            </div>
          )}
        </div>
        {!showHelp && showQuickStart && (
          <QuickStartVision
            // "done" dismisses like skip: the overview is saved client-side on click, and the wizard
            // no longer writes server roles, so without a dismissal it would reopen every load.
            onSkip={() => { if (visionStatus) dismissQuickStart(visionStatus, storage); setQuickStartOpen(false); }}
            onSaved={() => { if (visionStatus) dismissQuickStart(visionStatus, storage); setQuickStartOpen(false); api.visionStatus().then(setVisionStatus).catch(() => undefined); }}
          />
        )}
        {showHelp && (
          <div className="setup-help">
            <div className="setup-title">Operator not found on this computer</div>
            <p className="setup-lead">
              This page runs in your browser but needs the local <b>operator</b> running at <code>{base}</code>,
              and it isn’t responding. Start it once and this page reconnects on its own (it retries every second).
            </p>
            <ol className="setup-steps">
              <li>
                Open a terminal on <b>this machine</b> and run:
                <div className="cmd">
                  <code>{INSTALL_SH}</code>
                  <button className="small" onClick={copyInstall}>{copied ? "copied" : "copy"}</button>
                </div>
                <div className="hint">Windows (PowerShell): <code>{INSTALL_PS}</code></div>
              </li>
              <li>It installs an always-on background service (starts at login, restarts if it dies). No further steps — this page connects automatically.</li>
              <li>
                Operator already running somewhere else? Point this page at it:
                <div className="cmd">
                  <input type="text" value={baseInput} onChange={(e) => setBaseInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") applyBase(); }} placeholder={base} />
                  <button className="small" onClick={applyBase}>use this URL</button>
                </div>
              </li>
            </ol>
          </div>
        )}
        {!showHelp && (
          <div className="bodywrap">
            <div className="viewhost">
              {ui.view === "print" && <PrintView status={status} gates={g} call={call} base={base} onJob={() => setView("job")} onRuns={() => setView("runs")} />}
              {ui.view === "job" && <JobView status={status} gates={g} call={call} onGoPrint={() => setView("print")} />}
              {ui.view === "control" && <ControlView status={status} gates={g} call={call} gantryStep={ui.gantryStep} pistonStep={ui.pistonStep} setGantryStep={(s) => setUi((u) => ({ ...u, gantryStep: s }))} setPistonStep={(s) => setUi((u) => ({ ...u, pistonStep: s }))} />}
              {ui.view === "priming" && <PrimingView status={status} gates={g} call={call} onJob={() => setView("job")} onPrint={() => setView("print")} />}
              {ui.view === "runs" && <RunsView status={status} gates={g} call={call} base={base} />}
              {ui.view === "analysis" && <AnalysisView gates={g} call={call} base={base} />}
              {(ui.view === "settings" || ui.view === "cameras") && <SettingsView status={status} gates={g} call={call} base={base} onOpenQuickStart={() => setQuickStartOpen(true)} />}
            </div>
            <aside className={`dock${dock.open ? "" : " collapsed"}`} style={{ "--dock-w": `${dock.w}px` } as CSSProperties}>
              <div className="dock-resize" onPointerDown={dockDrag} title="drag to resize · snaps" />
              <MachineDock status={status} base={base} gates={g} call={call} view={ui.view} />
            </aside>
          </div>
        )}
        <StatusBar state={c?.state ?? "disconnected"} backend={c?.backend ?? "none"} pollHz={pollHz} reachable={reachable}
          estop={c?.telemetry?.estop_triggered ?? null} drivesReady={c?.telemetry?.drives_ready ?? null} heaterOn={c?.heater.on ?? null} heaterOnS={c?.heater.on_s ?? 0} heaterMaxS={c?.heater.max_on_s ?? 0}
          recActive={status?.recording.active ?? false} recRun={status?.recording.run ?? null} printState={r?.state ?? "idle"} version={version} build={opBuild} />
        {/* Headless: captures the assigned science camera on the operator's per-layer signal. */}
        <ScienceCaptureClient status={status} onError={setErr} />
        <OverviewTimelapseClient status={status} />
        {cameraStudio && <CameraStudio status={status} onClose={() => setCameraStudio(false)} />}
      </div>
    </ErrorBoundary>
  );
}
