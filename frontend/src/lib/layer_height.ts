// Layer-height resolution gate.
//
// The MachineMotion build-piston position readout is quantized to 0.1 mm (see the piston-sweep
// characterization, 2026-09-16): every /smartDrives/position value is a 0.1 mm multiple. A layer
// height that isn't a multiple of that quantum — 0.05 mm, 0.15 mm, ... — cannot be placed OR
// verified (it lands between two readable levels), so we don't expose it. Only 0.1 mm multiples,
// >= one quantum, are offered and accepted.

export const LAYER_HEIGHT_QUANTUM_MM = 0.1; // the position-readout floor

// The layer heights offered as presets — 0.1 mm multiples only (no 0.15 / sub-0.1).
export const LAYER_HEIGHTS_MM = [0.1, 0.2, 0.3];

/** Snap a requested layer height to the achievable/verifiable grid: the nearest multiple of the
 * 0.1 mm readout quantum, never below one quantum. Junk/zero/negative -> one quantum. */
export function snapLayerHeightMm(mm: number): number {
  if (!Number.isFinite(mm) || mm <= 0) return LAYER_HEIGHT_QUANTUM_MM;
  // Work in integer "tenths" and add a tiny epsilon so a half-quantum value (0.15 -> 1.4999… in
  // float) rounds up rather than down; floor at one quantum.
  const tenths = Math.max(1, Math.round(mm / LAYER_HEIGHT_QUANTUM_MM + 1e-9));
  return Number((tenths * LAYER_HEIGHT_QUANTUM_MM).toFixed(4));
}
