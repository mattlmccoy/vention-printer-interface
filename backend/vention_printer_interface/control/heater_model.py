from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HeaterExposure:
    powder_mass_g: float
    carbon_mass_g: float
    ink_mass_g: float
    ipa_mass_g: float
    energy_j: float
    time_s: float

    def sweep_speed_mm_s(self, pass_length_mm: float) -> float:
        return pass_length_mm / self.time_s if self.time_s > 0 else 0.0


def exposure(*, layer_mm: float, area_mm2: float, carbon_wt: float, powder_density_g_cm3: float,
             ink_carbon_wt: float, ipa_dhvap_j_g: float, section_power_w: float,
             passes: int = 1) -> HeaterExposure:
    """IPA-only heater exposure (spec §8). Ink is `ink_carbon_wt` carbon / the rest IPA.
    powder_mass = density * volume (per layer); carbon deposited = powder * wt/(1-wt) * `passes`
    (multi-pass stacks `passes` layers of ink evaporated in ONE heating pass); ink = carbon /
    ink_carbon_wt; IPA = ink * (1 - ink_carbon_wt); energy = IPA * dHvap; time = energy / power."""
    volume_cm3 = (area_mm2 * layer_mm) / 1000.0
    powder = powder_density_g_cm3 * volume_cm3
    carbon = (powder * carbon_wt / (1.0 - carbon_wt) if carbon_wt < 1.0 else 0.0) * max(passes, 1)
    ink = carbon / ink_carbon_wt if ink_carbon_wt > 0 else 0.0
    ipa = ink * (1.0 - ink_carbon_wt)
    energy = ipa * ipa_dhvap_j_g
    time = energy / section_power_w if section_power_w > 0 else 0.0
    return HeaterExposure(round(powder, 6), round(carbon, 6), round(ink, 6), round(ipa, 6),
                          round(energy, 3), round(time, 3))
