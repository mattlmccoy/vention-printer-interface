/** Mirror of backend heater_model.exposure(): IPA-only heater exposure (spec §8).
 *  Ink is `inkCarbonWt` carbon / the rest IPA; only IPA evaporates. Multi-pass jetting
 *  stacks `passes` layers of ink evaporated in ONE heating pass, so energy scales with passes. */

export interface HeaterExposure {
  powderMassG: number;
  carbonMassG: number;
  inkMassG: number;
  ipaMassG: number;
  energyJ: number;
  timeS: number;
  sweepSpeed(passLenMm: number): number;
}

export interface ExposureArgs {
  layerMm: number;
  areaMm2: number;
  carbonWt: number;
  powderDensityGCm3: number;
  inkCarbonWt: number;
  ipaDhvapJG: number;
  sectionPowerW: number;
  passes?: number;
}

const round = (x: number, n: number): number => {
  const f = 10 ** n;
  return Math.round(x * f) / f;
};

export function exposure(args: ExposureArgs): HeaterExposure {
  const { layerMm, areaMm2, carbonWt, powderDensityGCm3, inkCarbonWt, ipaDhvapJG,
    sectionPowerW, passes = 1 } = args;
  const volumeCm3 = (areaMm2 * layerMm) / 1000.0;
  const powder = powderDensityGCm3 * volumeCm3;
  const carbon = (carbonWt < 1.0 ? (powder * carbonWt) / (1.0 - carbonWt) : 0.0) * Math.max(passes, 1);
  const ink = inkCarbonWt > 0 ? carbon / inkCarbonWt : 0.0;
  const ipa = ink * (1.0 - inkCarbonWt);
  const energy = ipa * ipaDhvapJG;
  const time = sectionPowerW > 0 ? energy / sectionPowerW : 0.0;
  const timeS = round(time, 3);
  return {
    powderMassG: round(powder, 6),
    carbonMassG: round(carbon, 6),
    inkMassG: round(ink, 6),
    ipaMassG: round(ipa, 6),
    energyJ: round(energy, 3),
    timeS,
    sweepSpeed(passLenMm: number): number {
      return timeS > 0 ? passLenMm / timeS : 0.0;
    },
  };
}
