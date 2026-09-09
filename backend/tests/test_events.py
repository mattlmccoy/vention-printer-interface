from vention_printer_interface.control.events import EventLog


def test_ring_keeps_last_n_and_orders_oldest_first() -> None:
    log = EventLog(capacity=3)
    for i in range(5):
        log.append(f"e{i}", {"i": i})
    recent = log.recent(10)
    assert [e["label"] for e in recent] == ["e2", "e3", "e4"]
    assert recent[0]["data"] == {"i": 2} and "host_timestamp_ns" in recent[0]
    assert [e["label"] for e in log.recent(1)] == ["e4"]


def test_listener_fanout_survives_exceptions() -> None:
    log = EventLog()
    seen: list[str] = []
    log.add_sink(lambda label, data: seen.append(label))
    log.add_sink(lambda label, data: 1 / 0)
    log.append("x", {})
    assert seen == ["x"]
