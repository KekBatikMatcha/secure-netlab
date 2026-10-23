"""The one-command demo: its plan, and that the URLs it prints match the compose port bindings."""

from __future__ import annotations

from pathlib import Path

import demo
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_demo_plan_is_start_then_check_then_traffic() -> None:
    steps = demo.plan("python")
    assert [argv[0] for _, argv, _ in steps] == ["docker", "python", "python"]
    assert "--build" in steps[0][1] and "--wait" in steps[0][1]
    assert steps[1][1][1:] == ["-m", "automation", "check"]
    assert steps[2][1][1].endswith("demo_traffic.py")


def test_drift_exit_code_does_not_stop_the_demo_but_errors_do() -> None:
    steps = demo.plan("python")
    check_ok = steps[1][2]
    assert 1 in check_ok  # drift is expected on a modified lab
    assert 2 not in check_ok  # a collection error is a real failure
    assert 0 in steps[0][2]


def test_printed_urls_match_the_published_ports() -> None:
    compose = yaml.safe_load((ROOT / "compose" / "docker-compose.yml").read_text(encoding="utf-8"))
    grafana = compose["services"]["grafana"]["ports"]
    prometheus = compose["services"]["prometheus"]["ports"]
    assert "127.0.0.1:3000:3000" in grafana
    assert "127.0.0.1:9090:9090" in prometheus
    assert demo.GRAFANA_URL.startswith("http://127.0.0.1:3000/")
    assert demo.PROMETHEUS_URL.startswith("http://127.0.0.1:9090/")
