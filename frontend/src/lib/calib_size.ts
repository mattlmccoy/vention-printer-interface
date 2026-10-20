/** A calibration holds only at the photo size it was fitted on. The operator refuses to measure a
 *  print still of another size (vision/registration.py calibration_size_mismatch), so warn BEFORE a
 *  print when the science camera's resolution setting no longer matches the loaded calibration. */
export function calibrationSizeWarning(resolution: string, calib: [number, number] | null): string | null {
  if (!calib) return null;
  const [w, h] = resolution.split("x").map(Number);
  if (!(w > 0 && h > 0)) return null;
  if (w === calib[0] && h === calib[1]) return null;
  return `Science camera is set to ${w}×${h}, but the calibration was fitted on ${calib[0]}×${calib[1]} photos — `
    + "print stills will be stored but not measured. Set the resolution back, or recalibrate at this one.";
}
