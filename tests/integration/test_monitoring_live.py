"""Integration: Prometheus and Grafana against the live lab (make up). Requires Docker.

Checks that config passes promtool, that the monitor's metrics reach Prometheus, and that Grafana
is up. The state-based checks need a `check` run first (python -m automation check).
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
PROM_DIR = ROOT / "lab" / "prometheus"
PROMETHEUS = "http://127.0.0.1:9090"
GRAFANA = "http://127.0.0.1:3000"
PROM_IMAGE = "prom/prometheus:v3.5.0"  # same pinned image as compose


def _get_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _query(expr: str) -> list[dict[str, Any]]:
    url = f"{PROMETHEUS}/api/v1/query?query={urllib.parse.quote(expr)}"
    return _get_json(url)["data"]["result"]


def _wait_for(expr: str, want: int, timeout: float = 90.0) -> list[dict[str, Any]]:
    """Poll until the query returns at least `want` series (scrapes take up to 15 s)."""
    deadline = time.monotonic() + timeout
    result: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        result = _query(expr)
        if len(result) >= want:
            return result
        time.sleep(3)
    return result


def test_promtool_accepts_prometheus_config_and_alert_rules() -> None:
    # Mount the directory so prometheus.yml and its rule_files path resolve, like in compose.
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{PROM_DIR}:/etc/prometheus:ro",
        "--entrypoint", "promtool",
        PROM_IMAGE,
        "check", "config", "/etc/prometheus/prometheus.yml",
    ]
    import subprocess

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_prometheus_is_scraping_all_three_device_probes() -> None:
    series = _wait_for("lab_device_up", want=3)
    devices = {s["metric"]["device"] for s in series}
    assert devices == {"eng-ws", "app-server", "plc"}, series


def test_scrape_target_for_the_monitor_is_up() -> None:
    targets = _get_json(f"{PROMETHEUS}/api/v1/targets")["data"]["activeTargets"]
    monitor = [t for t in targets if t["labels"].get("job") == "lab-monitor"]
    assert monitor and all(t["health"] == "up" for t in monitor), monitor


def test_alert_rules_are_loaded_and_evaluating() -> None:
    groups = _get_json(f"{PROMETHEUS}/api/v1/rules")["data"]["groups"]
    names = {r["name"] for g in groups for r in g["rules"]}
    assert {"DeviceDown", "ConfigDriftHigh", "HighProbeLatencyP50", "BackupStale"} <= names
    assert all(r["health"] == "ok" for g in groups for r in g["rules"])


def test_backup_metrics_reach_prometheus_when_state_exists() -> None:
    state = ROOT / "reports" / "state.json"
    if not state.is_file():
        pytest.fail("no reports/state.json; run `python -m automation check` first")
    series = _wait_for("lab_backup_last_success_timestamp_seconds", want=1)
    assert {s["metric"]["device"] for s in series} >= {"router"}, series


def test_grafana_is_healthy_and_serves_the_provisioned_dashboard() -> None:
    health = _get_json(f"{GRAFANA}/api/health")
    assert health["database"] == "ok"
    search = _get_json(f"{GRAFANA}/api/search?query=Secure%20Netlab")
    assert any(item["uid"] == "lab-overview" for item in search), search
