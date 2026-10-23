"""One backup cycle (fetch, store, compare) and a simple scheduler loop."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from automation.bundle import ConfigBundle
from automation.drift import DriftReport, compare
from automation.fetch import Fetcher, FetchError
from automation.inventory import Device
from automation.store import BackupStore, BaselineStore


@dataclass(frozen=True)
class CycleResult:
    device: str
    status: str  # "stored" (new version), "unchanged", or "error"
    error: str | None = None
    report: DriftReport | None = None  # None when there is no baseline yet


def _now() -> datetime:
    return datetime.now(UTC)


def run_cycle(
    devices: Sequence[Device],
    fetcher: Fetcher,
    store: BackupStore,
    baseline: BaselineStore,
    when: datetime | None = None,
) -> list[CycleResult]:
    """Fetch every device once, store changed versions, and compare each with its baseline.

    One device failing does not stop the others.
    """
    stamp = when or _now()
    results: list[CycleResult] = []
    for device in devices:
        try:
            bundle = fetcher.fetch(device)
        except (FetchError, subprocess.TimeoutExpired) as exc:
            results.append(CycleResult(device.name, "error", error=str(exc)))
            continue
        status = "stored" if store.save(device.name, bundle, stamp) else "unchanged"
        results.append(
            CycleResult(device.name, status, report=_drift_for(device.name, bundle, baseline))
        )
    return results


def _drift_for(device: str, bundle: ConfigBundle, baseline: BaselineStore) -> DriftReport | None:
    approved = baseline.load(device)
    return compare(device, approved, bundle) if approved is not None else None


def run_scheduled(
    devices: Sequence[Device],
    fetcher: Fetcher,
    store: BackupStore,
    baseline: BaselineStore,
    *,
    every: float,
    cycles: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_results: Callable[[list[CycleResult]], None] | None = None,
) -> None:
    """Run run_cycle repeatedly, `every` seconds apart. cycles=None runs until interrupted."""
    done = 0
    while cycles is None or done < cycles:
        results = run_cycle(devices, fetcher, store, baseline)
        done += 1
        if on_results is not None:
            on_results(results)
        if cycles is None or done < cycles:
            sleep(every)
