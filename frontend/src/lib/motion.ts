// Parsers for a run's recorded CSVs (motion_profiles.csv, layer_accuracy.csv). Shared by the Runs
// charts and the print finish screen. Blank cells are "unknown" and never coerced to 0.

export type Metric = "pos" | "vel" | "accel";

export interface LayerAccuracy {
  layer: number | null;
  phase: string;
  commanded_mm: number | null;
  actual_mm: number | null;
  deviation_mm: number | null;
  commanded_cum_mm: number | null;
  actual_cum_mm: number | null;
}

export interface AccuracySummary {
  n: number;
  meanAbsDevMm: number | null;
  maxAbsDevMm: number | null;
  maxLayer: number | null; // the layer with the worst |deviation|
}

const PART_DROP_PHASES = new Set(["thin_precoat", "printing"]);

function num(cell: string | undefined): number | null {
  if (cell === undefined || cell.trim() === "") return null;
  const v = Number(cell);
  return Number.isFinite(v) ? v : null;
}

/** Split CSV text into a header row and data rows (simple comma split; our CSVs have no quoting). */
export function parseCsv(csv: string): { header: string[]; rows: string[][] } {
  const lines = csv.trim().split(/\r?\n/).filter((l) => l.length > 0);
  if (lines.length === 0) return { header: [], rows: [] };
  return { header: lines[0].split(","), rows: lines.slice(1).map((l) => l.split(",")) };
}

/** motion_profiles.csv -> one axis's series for a metric (pos_/vel_/accel_<axis>), blanks dropped. */
export function motionColumn(csv: string, metric: Metric, axis: number): number[] {
  const { header, rows } = parseCsv(csv);
  const idx = header.indexOf(`${metric}_${axis}`);
  if (idx < 0) return [];
  const out: number[] = [];
  for (const r of rows) {
    const v = num(r[idx]);
    if (v !== null) out.push(v);
  }
  return out;
}

/** True when motion_profiles.csv carries at least one native-speed sample (vspeed_*), i.e. the
 *  velocity series came from the controller's measured speed rather than finite differences. */
export function hasNativeSpeed(csv: string): boolean {
  const { header } = parseCsv(csv);
  return header.some((h) => h.startsWith("vspeed_"));
}

/** layer_accuracy.csv -> typed per-layer rows. */
export function parseLayerAccuracy(csv: string): LayerAccuracy[] {
  const { header, rows } = parseCsv(csv);
  const col = (name: string) => header.indexOf(name);
  const iLayer = col("layer");
  const iPhase = col("phase");
  const iCmd = col("commanded_mm");
  const iAct = col("actual_mm");
  const iDev = col("deviation_mm");
  const iCmdCum = col("commanded_cum_mm");
  const iActCum = col("actual_cum_mm");
  return rows.map((r) => ({
    layer: num(r[iLayer]),
    phase: r[iPhase] ?? "",
    commanded_mm: num(r[iCmd]),
    actual_mm: num(r[iAct]),
    deviation_mm: num(r[iDev]),
    commanded_cum_mm: num(r[iCmdCum]),
    actual_cum_mm: num(r[iActCum]),
  }));
}

/** Deviation stats over the part-drop layers (build-piston accuracy), mirroring the backend. */
export function layerAccuracySummary(rows: LayerAccuracy[]): AccuracySummary {
  const scored = rows.filter(
    (r) => PART_DROP_PHASES.has(r.phase) && r.deviation_mm !== null,
  );
  if (scored.length === 0) return { n: 0, meanAbsDevMm: null, maxAbsDevMm: null, maxLayer: null };
  const absDevs = scored.map((r) => Math.abs(r.deviation_mm as number));
  const mean = absDevs.reduce((a, b) => a + b, 0) / absDevs.length;
  let maxAbs = -1;
  let maxLayer: number | null = null;
  scored.forEach((r) => {
    const a = Math.abs(r.deviation_mm as number);
    if (a > maxAbs) {
      maxAbs = a;
      maxLayer = r.layer;
    }
  });
  return { n: scored.length, meanAbsDevMm: mean, maxAbsDevMm: maxAbs, maxLayer };
}
