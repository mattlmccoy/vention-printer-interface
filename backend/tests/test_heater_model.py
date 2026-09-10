from vention_printer_interface.control.heater_model import HeaterExposure, exposure


def test_ipa_exposure_energy_and_time() -> None:
    e: HeaterExposure = exposure(layer_mm=0.2, area_mm2=900.0, carbon_wt=0.15,
                                 powder_density_g_cm3=1.01, ink_carbon_wt=0.25,
                                 ipa_dhvap_j_g=663.0, section_power_w=75.0)
    assert round(e.powder_mass_g, 4) == 0.1818
    assert round(e.ipa_mass_g, 4) == 0.0962
    assert round(e.energy_j, 1) == 63.8
    assert round(e.time_s, 2) == 0.85


def test_sweep_speed_from_pass_length() -> None:
    e = exposure(layer_mm=0.2, area_mm2=900.0, carbon_wt=0.15, powder_density_g_cm3=1.01,
                 ink_carbon_wt=0.25, ipa_dhvap_j_g=663.0, section_power_w=75.0)
    assert round(e.sweep_speed_mm_s(pass_length_mm=30.0), 1) == round(30.0 / e.time_s, 1)


def test_multipass_scales_energy_and_time() -> None:
    kw = dict(layer_mm=0.2, area_mm2=900.0, carbon_wt=0.15, powder_density_g_cm3=1.01,
              ink_carbon_wt=0.25, ipa_dhvap_j_g=663.0, section_power_w=75.0)
    e1 = exposure(**kw)
    e2 = exposure(**kw, passes=2)
    assert round(e2.energy_j, 3) == round(e1.energy_j * 2, 3)
    assert round(e2.time_s, 3) == round(e1.time_s * 2, 3)
