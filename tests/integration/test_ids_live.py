"""Integration: Suricata against the live lab. Requires Docker and `make up`.

Covers rule loading, each demo scenario raising its expected alerts, and the allow-list for the
industrial rule (the monitor's probes must not trigger it).
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import demo_traffic
import pytest

from monitor.ids import count_alerts

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = ROOT / "lab" / "suricata" / "rules"
EVE = ROOT / "reports" / "suricata" / "eve.json"
PROMETHEUS = "http://127.0.0.1:9090"


def _sid_counts() -> Counter[int]:
    counts: Counter[int] = Counter()
    for alert, n in count_alerts(EVE).items():
        counts[int(alert.sid)] += n
    return counts


def test_engine_loads_every_lab_rule_without_errors() -> None:
    rule_lines = [
        line
        for line in (RULES_DIR / "lab.rules").read_text(encoding="utf-8").splitlines()
        if line.startswith("alert ")
    ]
    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{RULES_DIR}:/etc/suricata/rules:ro",
            "jasonish/suricata:7.0.11",
            "-T", "-v", "-S", "/etc/suricata/rules/lab.rules",
            "-c", "/etc/suricata/suricata.yaml",
        ],
        capture_output=True, text=True, timeout=180, check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert f"{len(rule_lines)} rules successfully loaded, 0 rules failed" in output, output


def test_engine_is_running_and_writing_eve_json() -> None:
    result = subprocess.run(
        ["docker", "compose", "-f", str(ROOT / "compose" / "docker-compose.yml"),
         "ps", "--status", "running", "--services"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert "suricata" in result.stdout.split(), result.stdout
    assert EVE.is_file(), "reports/suricata/eve.json missing; is the suricata service up?"


def test_each_demo_scenario_raises_its_expected_alerts() -> None:
    before = _sid_counts()
    assert demo_traffic.main(["all"]) == 0
    time.sleep(4)  # let Suricata flush eve.json
    after = _sid_counts()
    for name, scenario in demo_traffic.SCENARIOS.items():
        for sid in scenario.expected_sids:
            assert after[sid] > before[sid], f"{name}: SID {sid} did not fire"


def test_monitor_probes_do_not_trigger_the_industrial_rule() -> None:
    # The monitor (10.10.30.20) probes the PLC every cycle. It is on the allow list.
    monitor_hits = [
        line
        for line in EVE.read_text(encoding="utf-8", errors="replace").splitlines()
        if '"signature_id":1000001' in line and '"src_ip":"10.10.30.20"' in line
    ]
    assert not monitor_hits, monitor_hits[:2]


def test_prometheus_shows_ids_counts_by_sid() -> None:
    deadline = time.monotonic() + 90
    seen: set[str] = set()
    while time.monotonic() < deadline and not {"1000001", "1000005"} <= seen:
        url = f"{PROMETHEUS}/api/v1/query?query=" + urllib.parse.quote("lab_ids_alerts_total")
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))["data"]["result"]
        seen = {series["metric"]["sid"] for series in data}
        time.sleep(3)
    assert {"1000001", "1000005"} <= seen, seen
