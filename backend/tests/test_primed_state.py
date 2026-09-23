import dataclasses
from pathlib import Path

from vention_printer_interface.control.primed_state import (
    PrimedState,
    load_primed,
    plan_fingerprint,
    primed_status,
    save_primed,
)
from vention_printer_interface.control.print_settings import PrintSettings


def test_round_trip_save_load(tmp_path: Path) -> None:
    state = PrimedState(part_mm=12.5, feed_mm=48.0, captured_at=1700.0)
    save_primed(tmp_path, state)
    loaded = load_primed(tmp_path)
    assert loaded == state
    assert loaded is not None
    assert loaded.part_mm == 12.5 and loaded.feed_mm == 48.0
    assert loaded.captured_at == 1700.0


def test_to_from_dict_round_trip() -> None:
    state = PrimedState(part_mm=1.0, feed_mm=2.0, captured_at=3.0)
    assert PrimedState.from_dict(state.to_dict()) == state


def test_load_empty_root_returns_none(tmp_path: Path) -> None:
    assert load_primed(tmp_path) is None


# ---- P2: a primed bed belongs to ONE plan and is used up by a print ----------------------------

def _plan(n: int = 30, feed: float = 0.5, speed: float = 2.5) -> PrintSettings:
    base = PrintSettings()
    return dataclasses.replace(base, printing=dataclasses.replace(
        base.printing, n_layers=n, feed_thickness_mm=feed, part_speed=speed))


def test_fingerprint_changes_with_powder_but_not_with_speed() -> None:
    assert plan_fingerprint(_plan()) == plan_fingerprint(_plan(speed=9.0))  # speed: same powder
    assert plan_fingerprint(_plan()) != plan_fingerprint(_plan(n=31))
    assert plan_fingerprint(_plan()) != plan_fingerprint(_plan(feed=0.4))
    base = _plan()
    assert plan_fingerprint(base) != plan_fingerprint(
        dataclasses.replace(base, postcoat_enabled=not base.postcoat_enabled))


def _primed(fp: str | None, consumed: float | None = None) -> PrimedState:
    return PrimedState(part_mm=0.0, feed_mm=20.0, captured_at=100.0,
                       plan_fingerprint=fp, consumed_at=consumed)


def test_status_ready_only_for_the_same_unused_plan() -> None:
    plan = _plan()
    assert primed_status(None, plan)["state"] == "none"
    assert primed_status(_primed(plan_fingerprint(plan)), plan)["state"] == "ready"
    other = primed_status(_primed(plan_fingerprint(_plan(n=99))), plan)
    assert other["state"] == "other_plan" and "different" in other["reason"]
    used = primed_status(_primed(plan_fingerprint(plan), consumed=200.0), plan)
    assert used["state"] == "used" and "already" in used["reason"]


def test_a_legacy_capture_without_a_plan_is_unverified_never_ready() -> None:
    assert primed_status(_primed(None), _plan())["state"] == "unverified"


def test_old_state_files_still_load(tmp_path: Path) -> None:
    (tmp_path / ".primed.json").write_text('{"part_mm": 1, "feed_mm": 2, "captured_at": 3}')
    s = load_primed(tmp_path)
    assert s is not None and s.plan_fingerprint is None and s.consumed_at is None
