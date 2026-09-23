"""The print holds at the capture pose until that capture is STORED (or a timeout).

Before: a fixed capture_hold_s dwell (live plan 2.0 s) with no acknowledgement. In the Windows
lightweight camera mode the browser opens the science camera on demand at full resolution (~1-3 s),
so the carriage could move away mid-capture. Decision 2026-09-23: wait for the still.
"""

import dataclasses
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from tests.test_print_controller import _pc, make, wait
from vention_printer_interface.control.capture_gate import CAPTURE_TIMEOUT_S, capture_settled
from vention_printer_interface.control.print_settings import PrintSettings, Step, compile_print


def _captures_plan() -> PrintSettings:
    base = PrintSettings()
    return dataclasses.replace(
        base,
        printing=dataclasses.replace(base.printing, n_layers=2),
        capture_stages=("post_jet",),
        capture_stages_enabled=("post_jet",),
        capture_hold_s=2.0,
    )


# ---- compile_print ------------------------------------------------------------------------------

def test_each_capture_hold_is_followed_by_a_wait_for_the_still() -> None:
    steps = compile_print(_captures_plan())
    holds = [
        i for i, s in enumerate(steps) if s.kind == "dwell" and s.label == "camera capture hold"
    ]
    assert len(holds) == 2  # one post_jet capture per printing layer
    for i in holds:
        nxt = steps[i + 1]
        assert nxt.kind == "await_capture" and nxt.value == CAPTURE_TIMEOUT_S


def test_no_captures_no_wait() -> None:
    plan = dataclasses.replace(_captures_plan(), capture_stages_enabled=())
    assert not [s for s in compile_print(plan) if s.kind == "await_capture"]


# ---- PrintController ----------------------------------------------------------------------------

def _await(timeout: float = 10.0) -> Step:
    return Step(index=0, phase="printing", layer=1, kind="await_capture", value=timeout)


def test_await_capture_waits_until_the_still_is_stored() -> None:
    now = [0.0]
    stored = [False]
    rc = _pc(0.1, lambda: now[0])
    rc.capture_settled = lambda: stored[0]
    rc._issued_at = 0.0
    now[0] = 3.0
    assert rc._blocking_done(_await(), {}, now[0]) is False
    stored[0] = True
    assert rc._blocking_done(_await(), {}, now[0]) is True
    assert rc._capture_missed is False


def test_await_capture_times_out_and_flags_the_miss() -> None:
    now = [0.0]
    rc = _pc(0.1, lambda: now[0])
    rc.capture_settled = lambda: False
    rc._issued_at = 0.0
    now[0] = 9.9
    assert rc._blocking_done(_await(10.0), {}, now[0]) is False
    now[0] = 10.0
    assert rc._blocking_done(_await(10.0), {}, now[0]) is True
    assert rc._capture_missed is True


def test_without_a_capture_gate_the_print_never_waits() -> None:
    rc = _pc(0.1, lambda: 0.0)
    rc._issued_at = 0.0
    assert rc._blocking_done(_await(), {}, 0.0) is True


def test_a_missed_capture_is_recorded_and_the_print_continues() -> None:
    rc, c, _ = make()
    events: list[tuple[str, dict[str, Any]]] = []
    rc.on_event = lambda label, data: events.append((label, data))
    rc.capture_settled = lambda: False
    try:
        c.arm()
        steps = (
            Step(0, "printing", 1, "mark", None, None, "capture:post_jet", 0.0),
            Step(1, "printing", 1, "await_capture", None, 0.3, "wait for science still", 0.0),
            Step(2, "printing", 1, "mark", None, None, "layer_end", 0.0),
        )
        rc.start_macro("capture-wait", steps)
        assert wait(lambda: rc.snapshot()["state"] == "done", timeout=5.0)
        assert "capture_missed" in [label for label, _ in events]
    finally:
        c.stop()


# ---- the gate ------------------------------------------------------------------------------------

def test_gate_settled_rules() -> None:
    req = {"seq": 4}
    assert capture_settled(None, 0, consumer_alive=True) is True       # no capture requested
    assert capture_settled(req, 4, consumer_alive=True) is True        # this capture is stored
    assert capture_settled(req, 3, consumer_alive=True) is False       # pending -> wait
    assert capture_settled(req, 3, consumer_alive=False) is True       # nobody will capture


# ---- operator wiring -----------------------------------------------------------------------------

def _usable(h: int = 96, w: int = 128) -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.integers(0, 255, (h, w, 3), dtype=np.uint8)


def test_a_browser_upload_releases_the_wait(tmp_path: Path) -> None:
    import cv2
    from fastapi.testclient import TestClient

    from vention_printer_interface.api.app import create_app
    from vention_printer_interface.vision.frame_source import SimulatedFrameSource

    app = create_app(backend="none", experiments_root=tmp_path,
                     vision_source=SimulatedFrameSource(width=32, height=24))
    with TestClient(app) as c:
        c.post("/api/recording/start", json={"name": "gate"})
        c.post("/api/vision/science/client-heartbeat")  # a live browser capture client
        app.state.events.append("capture:post_jet", {"layer": 3, "print_layer": 1})
        settled: Callable[[], bool] = app.state.capture_settled
        assert settled() is False  # the browser owns it and hasn't stored it yet
        ok, buf = cv2.imencode(".png", _usable())
        assert ok
        r = c.post("/api/vision/science/capture?layer=3&stage=post_jet&cad_layer=1",
                   content=buf.tobytes(), headers={"content-type": "image/png"})
        assert r.status_code == 200
        assert settled() is True
        c.post("/api/recording/stop")


def test_no_capture_consumer_never_holds_the_print(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from vention_printer_interface.api.app import create_app

    app = create_app(backend="none", experiments_root=tmp_path)  # no camera, no browser client
    with TestClient(app):
        app.state.events.append("capture:post_jet", {"layer": 3, "print_layer": 1})
        assert app.state.capture_settled() is True


def test_the_operators_own_grab_releases_the_wait(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from vention_printer_interface.api.app import create_app
    from vention_printer_interface.vision.frame_source import SimulatedFrameSource

    app = create_app(backend="none", experiments_root=tmp_path,
                     vision_source=SimulatedFrameSource(width=32, height=24))
    with TestClient(app) as c:
        c.post("/api/recording/start", json={"name": "gate-server"})
        app.state.events.append("capture:post_jet", {"layer": 2, "print_layer": 1})
        t0 = time.monotonic()
        while not app.state.capture_settled() and time.monotonic() - t0 < 3:
            time.sleep(0.02)
        assert app.state.capture_settled() is True
        c.post("/api/recording/stop")


def test_the_printer_is_wired_to_the_gate(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from vention_printer_interface.api.app import create_app

    app = create_app(backend="none", experiments_root=tmp_path)
    with TestClient(app):
        assert app.state.printer.capture_settled is app.state.capture_settled
