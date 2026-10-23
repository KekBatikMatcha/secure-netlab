"""Backup state: event counting, error handling, and atomic persistence."""

from __future__ import annotations

from pathlib import Path

from automation.backup import CycleResult
from automation.bundle import ConfigBundle
from automation.drift import compare
from automation.state import apply_results, read_state, update_state

FIXTURES = Path(__file__).parent / "fixtures"


def _report(current: str):  # type: ignore[no-untyped-def]
    base = ConfigBundle.from_text((FIXTURES / "router_baseline.cfg").read_text("utf-8"))
    cur = ConfigBundle.from_text((FIXTURES / current).read_text("utf-8"))
    return compare("router", base, cur)


def test_stored_clean_cycle_sets_last_success_and_counts_a_version() -> None:
    result = CycleResult("router", "stored", report=_report("router_counters_only.cfg"))
    state = apply_results(None, [result], now=500.0)
    dev = state["devices"]["router"]
    assert dev["last_success"] == 500.0
    assert dev["versions_stored"] == 1
    assert dev["drift_events"] == 0
    assert dev["findings"] == {"high": 0, "medium": 0, "low": 0}


def test_error_increments_errors_and_keeps_last_success() -> None:
    ok = apply_results(None, [CycleResult("router", "unchanged")], now=100.0)
    failed = apply_results(ok, [CycleResult("router", "error", error="boom")], now=200.0)
    dev = failed["devices"]["router"]
    assert dev["errors"] == 1
    assert dev["last_success"] == 100.0


def test_drift_event_counts_new_or_changed_findings_not_persistent_ones() -> None:
    drift = CycleResult("router", "unchanged", report=_report("router_drift.cfg"))
    state = apply_results(None, [drift], now=1.0)
    assert state["devices"]["router"]["drift_events"] == 1

    # Same drift again on the next poll: still the same event.
    state = apply_results(state, [drift], now=2.0)
    assert state["devices"]["router"]["drift_events"] == 1

    # Clean poll clears the fingerprint; drift coming back is a new event.
    clean = CycleResult("router", "unchanged", report=_report("router_counters_only.cfg"))
    state = apply_results(state, [clean], now=3.0)
    assert state["devices"]["router"]["last_drift"] == ""
    state = apply_results(state, [drift], now=4.0)
    assert state["devices"]["router"]["drift_events"] == 2


def test_findings_are_counted_by_severity() -> None:
    result = CycleResult("router", "unchanged", report=_report("router_drift.cfg"))
    dev = apply_results(None, [result], now=1.0)["devices"]["router"]
    assert dev["findings"] == {"high": 2, "medium": 1, "low": 0}


def test_no_baseline_result_leaves_drift_fields_alone() -> None:
    result = CycleResult("router", "stored", report=None)
    dev = apply_results(None, [result], now=1.0)["devices"]["router"]
    assert dev["drift_events"] == 0
    assert dev["last_drift"] == ""


def test_update_state_persists_and_accumulates_across_calls(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    update_state(path, [CycleResult("router", "stored")], now=10.0)
    update_state(path, [CycleResult("router", "stored")], now=20.0)
    state = read_state(path)
    assert state is not None
    assert state["updated"] == 20.0
    assert state["devices"]["router"]["versions_stored"] == 2
    assert not (tmp_path / "state.tmp").exists()  # temp file replaced atomically


def test_read_state_returns_none_when_missing(tmp_path: Path) -> None:
    assert read_state(tmp_path / "nope.json") is None
