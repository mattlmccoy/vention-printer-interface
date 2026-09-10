from pathlib import Path

from vention_printer_interface.control.primed_state import (
    PrimedState,
    load_primed,
    save_primed,
)


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
