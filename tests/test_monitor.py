"""Monitor: TCP probes, Prometheus exporter, and probe loop. No Docker and no real network."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from prometheus_client import generate_latest

from automation.backup import CycleResult
from automation.bundle import ConfigBundle
from automation.drift import compare
from automation.state import apply_results, write_state
from monitor.app import load_targets, probe_loop
from monitor.exporter import METRIC_FAMILIES, build_registry
from monitor.probe import ProbeResult, Target, probe

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
PLC = Target("plc", "10.10.40.10", 502)


class FakeSocket:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def ticking_clock(step: float) -> Any:
    """Each call advances time by `step` seconds, so latency is deterministic."""
    now = [0.0]

    def clock() -> float:
        now[0] += step
        return now[0]

    return clock


# --- probe -----------------------------------------------------------------------------------


def test_successful_probe_reports_handshake_time_and_closes_socket() -> None:
    sock = FakeSocket()
    result = probe(PLC, connect=lambda *a, **k: sock, clock=ticking_clock(0.004))
    assert result == ProbeResult(ok=True, seconds=pytest.approx(0.004))
    assert sock.closed


def test_refused_or_timed_out_probe_is_a_failure_with_reason() -> None:
    def refused(*args: Any, **kwargs: Any) -> None:
        raise ConnectionRefusedError("connection refused")

    result = probe(PLC, connect=refused, clock=ticking_clock(0.1))
    assert not result.ok
    assert "refused" in result.error


def test_probe_passes_target_and_timeout_to_connector() -> None:
    seen: dict[str, Any] = {}

    def connect(address: tuple[str, int], timeout: float) -> FakeSocket:
        seen.update(address=address, timeout=timeout)
        return FakeSocket()

    probe(PLC, timeout=1.5, connect=connect)
    assert seen == {"address": ("10.10.40.10", 502), "timeout": 1.5}


# --- exporter --------------------------------------------------------------------------------


def _exposition(registry: Any) -> str:
    return generate_latest(registry).decode("utf-8")


def test_probe_metrics_record_up_latency_and_failures() -> None:
    registry, metrics = build_registry(Path("does-not-exist.json"))
    metrics.record("plc", ProbeResult(ok=True, seconds=0.004))
    metrics.record("app-server", ProbeResult(ok=False, seconds=2.0, error="timed out"))
    text = _exposition(registry)
    assert 'lab_device_up{device="plc"} 1.0' in text
    assert 'lab_device_up{device="app-server"} 0.0' in text
    assert 'lab_probe_failures_total{device="app-server"} 1.0' in text
    assert 'lab_probe_duration_seconds_count{device="plc"} 1.0' in text
    # A failed probe must not pollute the latency histogram.
    assert 'lab_probe_duration_seconds_count{device="app-server"}' not in text


def test_missing_state_file_reports_infinite_age_and_no_backup_series(tmp_path: Path) -> None:
    registry, _ = build_registry(tmp_path / "state.json")
    text = _exposition(registry)
    assert "lab_state_age_seconds +Inf" in text
    assert "lab_drift_findings{" not in text


def test_state_file_is_exported_with_cumulative_counters(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state = {
        "updated": 1_000.0,
        "devices": {
            "router": {
                "last_success": 990.0,
                "versions_stored": 3,
                "errors": 1,
                "drift_events": 2,
                "last_drift": "abc",
                "findings": {"high": 1, "medium": 0, "low": 0},
            }
        },
    }
    write_state(state_path, state)
    registry, _ = build_registry(state_path)
    # Freeze "now" by using the file's own timestamp: age should be the difference only.
    text = _exposition(registry)
    assert 'lab_drift_events_total{device="router"} 2.0' in text
    assert 'lab_backup_versions_total{device="router"} 3.0' in text
    assert 'lab_backup_errors_total{device="router"} 1.0' in text
    assert 'lab_drift_findings{device="router",severity="high"} 1.0' in text
    assert 'lab_backup_last_success_timestamp_seconds{device="router"} 990.0' in text


def test_state_age_grows_with_the_clock(tmp_path: Path) -> None:
    from monitor.exporter import StateCollector

    state_path = tmp_path / "state.json"
    write_state(state_path, {"updated": 1_000.0, "devices": {}})
    collector = StateCollector(state_path, clock=lambda: 1_100.0)
    # The age family is always first, even when the state has no devices.
    first = next(iter(collector.collect()))
    assert first.name == "lab_state_age_seconds"
    assert first.samples[0].value == pytest.approx(100.0)


# --- probe loop and config -------------------------------------------------------------------


def test_probe_loop_probes_every_target_each_cycle_and_sleeps_between() -> None:
    registry, metrics = build_registry(Path("missing.json"))
    calls: list[str] = []
    sleeps: list[float] = []

    def fake_probe(target: Target) -> ProbeResult:
        calls.append(target.name)
        return ProbeResult(ok=True, seconds=0.001)

    probe_loop(
        [PLC, Target("eng-ws", "10.10.30.10", 8080)],
        metrics,
        fake_probe,
        interval=15,
        sleep=sleeps.append,
        cycles=2,
    )
    assert calls == ["plc", "eng-ws", "plc", "eng-ws"]
    assert sleeps == [15]


def test_repo_targets_file_loads() -> None:
    targets = load_targets(ROOT / "monitor" / "targets.yaml")
    assert {t.name for t in targets} == {"eng-ws", "app-server", "plc"}


def test_targets_file_rejects_incomplete_entries(tmp_path: Path) -> None:
    bad = tmp_path / "targets.yaml"
    bad.write_text("targets:\n  - name: x\n    host: 1.2.3.4\n", encoding="utf-8")
    with pytest.raises(ValueError, match="needs name, host and port"):
        load_targets(bad)


def test_exported_families_match_the_declared_list(tmp_path: Path) -> None:
    """Every family in METRIC_FAMILIES is really exported, and nothing else is."""
    from prometheus_client.parser import text_string_to_metric_families

    state_path = tmp_path / "state.json"
    results = [
        CycleResult("router", "stored", report=compare(
            "router",
            ConfigBundle.from_text((FIXTURES / "router_baseline.cfg").read_text("utf-8")),
            ConfigBundle.from_text((FIXTURES / "router_drift.cfg").read_text("utf-8")),
        )),
        CycleResult("plc", "error", error="boom"),
    ]
    write_state(state_path, apply_results(None, results, now=1_000.0))
    registry, metrics = build_registry(state_path)
    metrics.record("plc", ProbeResult(ok=True, seconds=0.002))
    metrics.record("plc", ProbeResult(ok=False, seconds=1.0, error="x"))

    # Ignore the "<name>_created" timestamp helpers that prometheus_client adds to counters.
    exported = {
        f.name
        for f in text_string_to_metric_families(_exposition(registry))
        if not f.name.endswith("_created")
    }
    assert exported == set(METRIC_FAMILIES)
