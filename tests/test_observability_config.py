"""Static checks on the Prometheus and Grafana config. Catch broken rules before deploy.

The most useful check here: every metric name used in an alert or dashboard must be one that
the exporter really produces. A typo would otherwise be an empty panel or a silent alert.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from monitor.exporter import METRIC_FAMILIES

ROOT = Path(__file__).resolve().parents[1]
PROM = ROOT / "lab" / "prometheus"
GRAFANA = ROOT / "lab" / "grafana"
DASHBOARD = GRAFANA / "dashboards" / "lab-overview.json"

_METRIC = re.compile(r"\blab_[a-z_]+")
_SUFFIXES = ("_bucket", "_sum", "_count", "_total")


def _base_name(metric: str) -> str:
    """Map an exposed sample name back to its family name, e.g. lab_probe_failures_total."""
    for suffix in _SUFFIXES:
        if metric.endswith(suffix):
            return metric[: -len(suffix)]
    return metric


def _referenced(text: str) -> set[str]:
    return {_base_name(m) for m in _METRIC.findall(text)}


def _alerts() -> list[dict[str, Any]]:
    data = yaml.safe_load((PROM / "alerts.yml").read_text(encoding="utf-8"))
    return [rule for group in data["groups"] for rule in group["rules"]]


def test_alert_rules_are_well_formed() -> None:
    rules = _alerts()
    names = [r["alert"] for r in rules]
    assert len(names) == len(set(names)), "alert names must be unique"
    for rule in rules:
        assert rule["expr"].strip(), rule["alert"]
        assert rule["labels"]["severity"] in {"critical", "warning"}, rule["alert"]
        assert rule["annotations"]["summary"], rule["alert"]


def test_alert_rules_only_use_exported_metrics() -> None:
    text = "\n".join(r["expr"] for r in _alerts())
    unknown = _referenced(text) - set(METRIC_FAMILIES)
    assert not unknown, f"alerts reference metrics the exporter does not export: {unknown}"


def test_dashboard_only_uses_exported_metrics() -> None:
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    exprs = [t["expr"] for p in dashboard["panels"] for t in p.get("targets", [])]
    unknown = _referenced("\n".join(exprs)) - set(METRIC_FAMILIES)
    assert not unknown, f"dashboard references unknown metrics: {unknown}"


def test_dashboard_is_valid_and_uses_the_provisioned_datasource() -> None:
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    assert dashboard["uid"] == "lab-overview"
    assert len(dashboard["panels"]) >= 8
    ids = [p["id"] for p in dashboard["panels"]]
    assert len(ids) == len(set(ids)), "panel ids must be unique"

    source = GRAFANA / "provisioning" / "datasources" / "prometheus.yml"
    datasource = yaml.safe_load(source.read_text(encoding="utf-8"))
    uid = datasource["datasources"][0]["uid"]
    for panel in dashboard["panels"]:
        assert panel["datasource"]["uid"] == uid, panel["title"]
        assert panel["targets"], panel["title"]


def test_prometheus_scrapes_the_monitor_and_loads_the_alert_file() -> None:
    config = yaml.safe_load((PROM / "prometheus.yml").read_text(encoding="utf-8"))
    assert "/etc/prometheus/alerts.yml" in config["rule_files"]
    targets = [
        t
        for job in config["scrape_configs"]
        for sc in job["static_configs"]
        for t in sc["targets"]
    ]
    assert "monitor:9101" in targets
