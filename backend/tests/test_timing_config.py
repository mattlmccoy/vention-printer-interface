"""Persistent print-timing config (install-independent, like paths_config)."""

from __future__ import annotations

from pathlib import Path

from vention_printer_interface.timing_config import (
    TimingConfig,
    load_timing,
    save_timing,
)


def test_absent_or_malformed_file_yields_empty(tmp_path: Path) -> None:
    assert load_timing(tmp_path / "nope.json") == TimingConfig()
    bad = tmp_path / "timing.json"
    bad.write_text("{ not json")
    assert load_timing(bad) == TimingConfig()


def test_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "timing.json"
    save_timing(TimingConfig(print_min_wait_s=0.08, print_poll_interval_s=0.05), p)
    got = load_timing(p)
    assert got.print_min_wait_s == 0.08
    assert got.print_poll_interval_s == 0.05


def test_partial_and_out_of_range_ignored(tmp_path: Path) -> None:
    p = tmp_path / "timing.json"
    # only one field set; a negative/zero or absurd value is dropped (kept None)
    save_timing(TimingConfig(print_min_wait_s=0.1, print_poll_interval_s=None), p)
    got = load_timing(p)
    assert got.print_min_wait_s == 0.1 and got.print_poll_interval_s is None
    (tmp_path / "bad2.json").write_text('{"print_min_wait_s": -1, "print_poll_interval_s": 99}')
    got2 = load_timing(tmp_path / "bad2.json")
    assert got2.print_min_wait_s is None and got2.print_poll_interval_s is None  # both out of range
