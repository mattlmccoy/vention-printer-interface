/** Piston max-travel calibration (Settings → Pistons): the operator jogs a piston to its physical
 *  stop, then records that position as the piston's usable max. Pure helper below; the view wires
 *  jog (api.move rel) + set (api.setPrintSettings) + live position (status telemetry). */

export type PistonField = "build_piston_max_mm" | "feed_piston_max_mm";

/** The setPrintSettings patch to record the current piston position as its max travel from home.
 *  Snaps to the 0.1 mm encoder readout and clamps to [0, hardMax] (the mechanical actuator limit). */
export function pistonMaxPatch(
  field: PistonField, positionMm: number, hardMaxMm = 145,
): Record<string, number> {
  const snapped = Math.round(positionMm * 10) / 10;
  return { [field]: Math.max(0, Math.min(hardMaxMm, snapped)) };
}
