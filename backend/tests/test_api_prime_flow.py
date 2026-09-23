"""P2: a primed bed belongs to the plan it was primed for, and a print uses it up.

START on a bed primed for a different plan, on an already-used bed, or on a capture that predates
plan recording is refused (409) unless the operator overrides with ``accept_prime_risk``. Never
primed stays a hard refusal. (The simulator's feed is unhomed, so every start here also carries
``accept_feed_risk`` -- the powder budget is tested in test_api_feed_budget.py.)
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_api_feed_budget import PLAN, _connect_arm_prime
from vention_printer_interface.api.app import create_app

FEED_OK = {"accept_feed_risk": True}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def client(root: Path) -> Iterator[TestClient]:
    app = create_app(backend="none", experiments_root=root, poll_interval_s=0.05,
                     print_min_wait_s=0.1, print_step_timeout_s=5.0)
    with TestClient(app) as c:
        yield c


def _status(c: TestClient) -> dict[str, str]:
    s: dict[str, str] = c.get("/api/primed").json()["status"]
    return s


def test_never_primed_reports_none(client: TestClient) -> None:
    r = client.get("/api/primed").json()
    assert r["primed"] is None and r["status"]["state"] == "none"


def test_capture_is_ready_for_the_plan_it_was_primed_for(client: TestClient) -> None:
    _connect_arm_prime(client)
    assert _status(client)["state"] == "ready"


def test_changing_the_powder_plan_after_priming_blocks_start(client: TestClient) -> None:
    _connect_arm_prime(client)
    client.put("/api/print-settings", json={"printing": {**PLAN["printing"], "n_layers": 8}})
    assert _status(client)["state"] == "other_plan"
    r = client.post("/api/print/start", json=FEED_OK)
    assert r.status_code == 409 and "different plan" in r.json()["detail"]
    ok = client.post("/api/print/start", json={**FEED_OK, "accept_prime_risk": True})
    assert ok.status_code == 200


def test_a_speed_change_does_not_invalidate_the_primed_bed(client: TestClient) -> None:
    _connect_arm_prime(client)
    client.put("/api/print-settings", json={"printing": {**PLAN["printing"], "part_speed": 15}})
    assert _status(client)["state"] == "ready"


def test_a_print_uses_up_the_primed_bed(client: TestClient) -> None:
    _connect_arm_prime(client)
    assert client.post("/api/print/start", json=FEED_OK).status_code == 200
    client.post("/api/print/abort")
    assert _status(client)["state"] == "used"
    r = client.post("/api/print/start", json=FEED_OK)
    assert r.status_code == 409 and "already started" in r.json()["detail"]
    # re-priming makes it ready again
    assert client.post("/api/primed/capture").status_code == 200
    assert _status(client)["state"] == "ready"


def test_a_legacy_capture_is_unverified_and_needs_the_override(client: TestClient,
                                                               root: Path) -> None:
    _connect_arm_prime(client)
    legacy = {"part_mm": 0.0, "feed_mm": 20.0, "captured_at": 1.0}
    (root / ".primed.json").write_text(json.dumps(legacy))
    # a restart reads the legacy file
    app = create_app(backend="none", experiments_root=root)
    with TestClient(app) as c:
        assert _status(c)["state"] == "unverified"


def test_no_primed_bed_is_refused_even_with_the_override(client: TestClient) -> None:
    client.post("/api/connect", json={"backend": "simulated"})
    client.post("/api/arm")
    r = client.post("/api/print/start",
                    json={**FEED_OK, "accept_prime_risk": True})
    assert r.status_code == 409 and "prime" in r.json()["detail"].lower()
