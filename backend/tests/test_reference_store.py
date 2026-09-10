from pathlib import Path

from vention_printer_interface.control.reference_store import load_reference, save_reference


def test_round_trip(tmp_path: Path) -> None:
    save_reference(tmp_path, {1, 2, 4}, {1: 0.0, 2: 20.0, 3: 0.0, 4: 930.0})
    axes, positions = load_reference(tmp_path)  # type: ignore[misc]
    assert axes == {1, 2, 4}
    assert positions == {1: 0.0, 2: 20.0, 3: 0.0, 4: 930.0}


def test_missing_returns_none(tmp_path: Path) -> None:
    assert load_reference(tmp_path) is None


def test_corrupt_returns_none(tmp_path: Path) -> None:
    (tmp_path / ".reference.json").write_text("{not json")
    assert load_reference(tmp_path) is None
