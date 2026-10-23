"""Integration: back up the live lab and compare with the committed baselines (golden/).

Needs the lab running (make up) and baselines accepted once:
    python -m automation baseline router
    python -m automation baseline plc
"""

from __future__ import annotations

from pathlib import Path

import pytest

from automation.backup import run_cycle
from automation.fetch import DockerExecFetcher
from automation.inventory import load_inventory
from automation.store import BackupStore, BaselineStore

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]


def test_live_backup_matches_committed_baseline(tmp_path: Path) -> None:
    devices = load_inventory(ROOT / "inventory" / "devices.yaml")
    baseline = BaselineStore(ROOT / "golden")
    missing = [d.name for d in devices if baseline.load(d.name) is None]
    if missing:
        pytest.fail(f"no baseline for {missing}; run `python -m automation baseline <device>`")

    fetcher = DockerExecFetcher(ROOT / "compose" / "docker-compose.yml")
    results = run_cycle(devices, fetcher, BackupStore(tmp_path / "backups"), baseline)

    errors = [r for r in results if r.status == "error"]
    assert not errors, [r.error for r in errors]
    drifted = [r.report.to_text() for r in results if r.report and r.report.has_drift]
    assert not drifted, "\n".join(drifted)


def test_live_router_firewall_has_default_drop() -> None:
    fetcher = DockerExecFetcher(ROOT / "compose" / "docker-compose.yml")
    devices = load_inventory(ROOT / "inventory" / "devices.yaml")
    (router,) = [d for d in devices if d.name == "router"]
    bundle = fetcher.fetch(router)
    assert ":FORWARD DROP" in bundle.sections["firewall"]
