"""Park macros (spec §6) compiled to the same Step list a print uses.

load_cart: home every axis, then drive both pistons to the bottom of their (possibly tightened)
travel so the build cart can be loaded; the operator then jogs the pistons into place by hand.
clear_bed: home every axis.
"""

from __future__ import annotations

from vention_printer_interface.control.print_settings import FEED, PART, Step
from vention_printer_interface.control.safety import SafetyLimits

MACROS: dict[str, str] = {
    "load_cart": "home gantries, then both pistons to the bottom of travel",
    "clear_bed": "home every axis",
}


def macro_steps(name: str, limits: SafetyLimits) -> tuple[Step, ...]:
    if name not in MACROS:
        raise KeyError(f"unknown macro {name!r}; known: {sorted(MACROS)}")
    out: list[Step] = []

    def add(kind: str, axis: int | None = None, value: float | None = None) -> None:
        out.append(Step(len(out), name, 0, kind, axis, value, "", 0.0))

    add("home_all")
    add("wait")
    if name == "load_cart":
        for axis in (FEED, PART):
            add("set_speed", axis, limits.max_speed[axis])
            add("set_accel", axis, limits.max_accel[axis])
            add("move_abs", axis, limits.travel_max[axis])
        add("wait")
    return tuple(out)
