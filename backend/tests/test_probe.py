import json
from pathlib import Path

from vention_printer_interface.probe import main, run_probe


def test_run_probe_simulated_is_read_only() -> None:
    report = run_probe(backend="simulated", ip=None, samples=3, interval_s=0.0, mqtt_capture_s=0.0)
    assert report["backend"] == "simulated"
    assert report["health"]["version"] == "2.14.1"
    assert len(report["samples"]) == 3
    assert set(report["samples"][0]["positions"]) == {"1", "2", "3", "4"}
    assert "endstops" in report and "drive_configs" in report and "mqtt" in report
    assert report["mqtt"]["estop/status"] == "false"
    assert report["writes_performed"] == []


def test_main_writes_report(tmp_path: Path) -> None:
    out = tmp_path / "probe.json"
    rc = main(["--simulated", "--samples", "1", "--mqtt-seconds", "0", "--output", str(out)])
    assert rc == 0
    assert json.loads(out.read_text())["samples"]


def test_main_unreachable_returns_2() -> None:
    assert main(["--ip", "192.0.2.1", "--samples", "1", "--mqtt-seconds", "0"]) == 2
