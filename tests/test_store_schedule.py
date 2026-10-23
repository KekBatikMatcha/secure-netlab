"""Versioned storage, one backup cycle, and the scheduler loop. Uses fake fetchers, no Docker."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from automation.backup import run_cycle, run_scheduled
from automation.bundle import ConfigBundle
from automation.cli import exit_code
from automation.fetch import FetchError
from automation.inventory import Device
from automation.store import BackupStore, BaselineStore

FIXTURES = Path(__file__).parent / "fixtures"
WHEN = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
ROUTER = Device("router", "router", {"firewall": "iptables-save", "listeners": "netstat -tln"})
PLC = Device("plc", "plc", {"listeners": "netstat -tln"})


def load(name: str) -> ConfigBundle:
    return ConfigBundle.from_text((FIXTURES / name).read_text(encoding="utf-8"))


class FakeFetcher:
    """Returns a canned bundle per device name, or raises the canned exception."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def fetch(self, device: Device) -> ConfigBundle:
        self.calls.append(device.name)
        value = self.responses[device.name]
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture
def stores(tmp_path: Path) -> tuple[BackupStore, BaselineStore]:
    return BackupStore(tmp_path / "backups"), BaselineStore(tmp_path / "golden")


def test_first_cycle_stores_a_version_and_has_no_drift_without_baseline(
    stores: tuple[BackupStore, BaselineStore],
) -> None:
    store, baseline = stores
    fetcher = FakeFetcher({"router": load("router_baseline.cfg")})
    (result,) = run_cycle([ROUTER], fetcher, store, baseline, WHEN)
    assert result.status == "stored"
    assert result.report is None
    assert store.versions("router")[0].name == "20261023T120000Z.cfg"


def test_identical_config_is_unchanged_and_not_stored_twice(
    stores: tuple[BackupStore, BaselineStore],
) -> None:
    store, baseline = stores
    fetcher = FakeFetcher({"router": load("router_baseline.cfg")})
    run_cycle([ROUTER], fetcher, store, baseline, WHEN)
    (second,) = run_cycle([ROUTER], fetcher, store, baseline, WHEN.replace(hour=13))
    assert second.status == "unchanged"
    assert len(store.versions("router")) == 1


def test_counter_only_change_does_not_create_a_new_version(
    stores: tuple[BackupStore, BaselineStore],
) -> None:
    store, baseline = stores
    fetcher = FakeFetcher({"router": load("router_baseline.cfg")})
    run_cycle([ROUTER], fetcher, store, baseline, WHEN)
    fetcher.responses["router"] = load("router_counters_only.cfg")
    (result,) = run_cycle([ROUTER], fetcher, store, baseline, WHEN.replace(hour=13))
    assert result.status == "unchanged"
    assert len(store.versions("router")) == 1


def test_drift_against_baseline_is_stored_and_reported(
    stores: tuple[BackupStore, BaselineStore],
) -> None:
    store, baseline = stores
    baseline.accept("router", load("router_baseline.cfg"))
    fetcher = FakeFetcher({"router": load("router_drift.cfg")})
    (result,) = run_cycle([ROUTER], fetcher, store, baseline, WHEN)
    assert result.status == "stored"
    assert result.report is not None and result.report.has_drift
    assert len(result.report.findings) == 3
    assert exit_code([result]) == 1


def test_clean_cycle_exits_zero(stores: tuple[BackupStore, BaselineStore]) -> None:
    store, baseline = stores
    baseline.accept("router", load("router_baseline.cfg"))
    fetcher = FakeFetcher({"router": load("router_counters_only.cfg")})
    results = run_cycle([ROUTER], fetcher, store, baseline, WHEN)
    assert exit_code(results) == 0


def test_failed_device_does_not_stop_others_and_stores_nothing_for_it(
    stores: tuple[BackupStore, BaselineStore],
) -> None:
    store, baseline = stores
    fetcher = FakeFetcher(
        {"router": FetchError("router/firewall: exit 1"), "plc": load("router_baseline.cfg")}
    )
    router_result, plc_result = run_cycle([ROUTER, PLC], fetcher, store, baseline, WHEN)
    assert router_result.status == "error"
    assert "exit 1" in (router_result.error or "")
    assert plc_result.status == "stored"
    assert store.versions("router") == []
    assert exit_code([router_result, plc_result]) == 2


def test_versions_accumulate_in_order_when_config_changes(
    stores: tuple[BackupStore, BaselineStore],
) -> None:
    store, baseline = stores
    fetcher = FakeFetcher({"router": load("router_baseline.cfg")})
    run_cycle([ROUTER], fetcher, store, baseline, WHEN)
    fetcher.responses["router"] = load("router_drift.cfg")
    run_cycle([ROUTER], fetcher, store, baseline, WHEN.replace(hour=13))
    assert len(store.versions("router")) == 2
    assert store.latest_bundle("router") == load("router_drift.cfg").normalized()


def test_save_never_overwrites_a_version_taken_in_the_same_second(tmp_path: Path) -> None:
    store = BackupStore(tmp_path)
    first = store.save("router", load("router_baseline.cfg"), WHEN)
    second = store.save("router", load("router_drift.cfg"), WHEN)
    assert first is not None and second is not None
    assert first != second
    assert first.exists() and second.exists()


def test_baseline_accept_then_load_round_trips(tmp_path: Path) -> None:
    baseline = BaselineStore(tmp_path)
    baseline.accept("router", load("router_baseline.cfg"))
    assert baseline.load("router") == load("router_baseline.cfg").normalized()
    assert baseline.load("plc") is None


def test_scheduler_sleeps_between_cycles_but_not_after_the_last(
    stores: tuple[BackupStore, BaselineStore],
) -> None:
    store, baseline = stores
    fetcher = FakeFetcher({"router": load("router_baseline.cfg")})
    sleeps: list[float] = []
    seen: list[int] = []
    run_scheduled(
        [ROUTER],
        fetcher,
        store,
        baseline,
        every=300,
        cycles=3,
        sleep=sleeps.append,
        on_results=lambda results: seen.append(len(results)),
    )
    assert sleeps == [300, 300]
    assert fetcher.calls == ["router", "router", "router"]
    assert seen == [1, 1, 1]
