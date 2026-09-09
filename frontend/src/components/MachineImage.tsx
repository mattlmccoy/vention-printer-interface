import { useEffect, useState } from "react";
import { DEFAULT_CALIB, loadCalibration, parseCalibration, pistonPoint, POINTS, railPoint, saveCalibration, setPoint, type Calibration } from "../lib/machine_calib.ts";
import { TRAVEL_MM, type StatusPayload } from "../lib/telemetry.ts";
import { Elevation } from "./Elevation.tsx";

const storage = typeof localStorage === "undefined" ? null : localStorage;
const IMG = `${import.meta.env.BASE_URL}machine/printer.png`;
const CAL = `${import.meta.env.BASE_URL}machine/calibration.json`;

/** The lab wireframe with live markers: carriages along the rails, piston tops, heater. If the
 *  image is missing it falls back to the schematic. Calibrate mode: click the eight points in
 *  order; the result is kept in localStorage and can be copied as JSON into calibration.json. */
export function MachineImage({ status, partZeroMm }: { status: StatusPayload | null; partZeroMm: number | null }) {
  const [ok, setOk] = useState<boolean | null>(null);
  const [fileCal, setFileCal] = useState<Calibration>(DEFAULT_CALIB);
  const [cal, setCal] = useState<Calibration | null>(() => loadCalibration(storage));
  const [calib, setCalib] = useState<number | null>(null); // index of the next point to click
  useEffect(() => {
    const im = new Image();
    im.onload = () => setOk(true); im.onerror = () => setOk(false); im.src = IMG;
    fetch(CAL).then((r) => (r.ok ? r.json() : null)).then((j) => { if (j) setFileCal(parseCalibration(j)); }).catch(() => undefined);
  }, []);
  if (ok === false || ok === null) return <Elevation status={status} partZeroMm={partZeroMm} />;
  const c = cal ?? fileCal;
  const t = status?.controller.telemetry ?? null;
  const p = (a: number) => t?.positions[String(a)] ?? 0;
  const mv = (a: number) => (t ? t.motion_complete[String(a)] === false : false);
  const heater = status?.controller.heater.on ?? null;
  const ph = railPoint(c.rails.printhead, p(3), TRAVEL_MM[3]);
  const rc = railPoint(c.rails.recoater, p(4), TRAVEL_MM[4]);
  const feed = pistonPoint(c.pistons.feed, p(2));
  const build = pistonPoint(c.pistons.build, p(1));
  const onClick = (e: React.MouseEvent<SVGSVGElement>) => {
    if (calib === null) return;
    const r = e.currentTarget.getBoundingClientRect();
    const pt = { x: Math.round(((e.clientX - r.left) / r.width) * c.image.w), y: Math.round(((e.clientY - r.top) / r.height) * c.image.h) };
    const next = setPoint(c, POINTS[calib][0], pt);
    setCal(next); saveCalibration(storage, next);
    setCalib(calib + 1 < POINTS.length ? calib + 1 : null);
  };
  const hcls = heater === true ? "el-heater-on" : heater === false ? "el-heater-off" : "el-heater-unk";
  return (
    <div className="mimg">
      <svg viewBox={`0 0 ${c.image.w} ${c.image.h}`} onClick={onClick} style={{ cursor: calib !== null ? "crosshair" : "default" }} role="img" aria-label="printer with live positions">
        <image href={IMG} width={c.image.w} height={c.image.h} />
        <line className="mk-rail" x1={c.rails.printhead.x0} y1={c.rails.printhead.y0} x2={c.rails.printhead.x1} y2={c.rails.printhead.y1} />
        <line className="mk-rail" x1={c.rails.recoater.x0} y1={c.rails.recoater.y0} x2={c.rails.recoater.x1} y2={c.rails.recoater.y1} />
        <line className="mk-rail" x1={c.pistons.feed.x} y1={c.pistons.feed.y0} x2={c.pistons.feed.x} y2={c.pistons.feed.y1} />
        <line className="mk-rail" x1={c.pistons.build.x} y1={c.pistons.build.y0} x2={c.pistons.build.x} y2={c.pistons.build.y1} />
        {t && <>
          <circle className={`el-ph${mv(3) ? " el-moving" : ""}`} cx={ph.x} cy={ph.y} r={16} />
          <circle className={`el-rc${mv(4) ? " el-moving" : ""}`} cx={rc.x} cy={rc.y} r={16} />
          <circle className={hcls} cx={rc.x + c.heater_offset_px.dx} cy={rc.y + c.heater_offset_px.dy} r={9} />
          <rect className={`el-feed${mv(2) ? " el-moving" : ""}`} x={feed.x - 26} y={feed.y - 4} width={52} height={8} rx={2} />
          <rect className={`el-build${mv(1) ? " el-moving" : ""}`} x={build.x - 26} y={build.y - 4} width={52} height={8} rx={2} />
        </>}
        {calib !== null && <text className="mk-hint" x={20} y={c.image.h - 24}>click: {POINTS[calib][1]} ({calib + 1}/{POINTS.length})</text>}
      </svg>
      <div className="row" style={{ marginTop: 8 }}>
        {calib === null ? <button className="small" onClick={() => setCalib(0)}>calibrate markers</button> : <button className="small" onClick={() => setCalib(null)}>stop</button>}
        {cal && <button className="small" onClick={() => { navigator.clipboard?.writeText(JSON.stringify(cal, null, 2)).catch(() => undefined); }}>copy calibration JSON</button>}
        {cal && <button className="small" onClick={() => { setCal(null); saveCalibration(storage, null); }}>reset to file</button>}
        <span className="hint">markers follow the machine; calibrate once against the real photo</span>
      </div>
    </div>
  );
}
