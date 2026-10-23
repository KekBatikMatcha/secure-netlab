"""Prometheus exporter: live probe metrics plus metrics read from the backup state file.

Two sources, one registry:
  * ProbeMetrics: updated by the probe loop (device up/down, latency, failures)
  * StateCollector: read from reports/state.json on every scrape (backups and drift)
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric

from automation.state import SEVERITIES, read_state
from monitor.ids import count_alerts
from monitor.probe import ProbeResult

# Base names of every family this exporter produces. Dashboards and alert rules must only use these
# (checked by tests/test_observability_config.py).
METRIC_FAMILIES: tuple[str, ...] = (
    "lab_device_up",
    "lab_probe_duration_seconds",
    "lab_probe_failures",
    "lab_probes",
    "lab_drift_events",
    "lab_drift_findings",
    "lab_backup_versions",
    "lab_backup_errors",
    "lab_backup_last_success_timestamp_seconds",
    "lab_state_age_seconds",
    "lab_ids_alerts",
    "lab_ids_eve_age_seconds",
)

# Covers LAN handshakes (about 1 ms) up to slow or saturated links (2.5 s).
LATENCY_BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)


class ProbeMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.up = Gauge(
            "lab_device_up", "1 if the last TCP probe succeeded", ["device"], registry=registry
        )
        self.duration = Histogram(
            "lab_probe_duration_seconds",
            "TCP connect time of successful probes",
            ["device"],
            buckets=LATENCY_BUCKETS,
            registry=registry,
        )
        self.failures = Counter(
            "lab_probe_failures", "Failed TCP probes", ["device"], registry=registry
        )
        self.probes = Counter("lab_probes", "TCP probes attempted", ["device"], registry=registry)

    def record(self, device: str, result: ProbeResult) -> None:
        self.probes.labels(device).inc()
        self.up.labels(device).set(1 if result.ok else 0)
        if result.ok:
            self.duration.labels(device).observe(result.seconds)
        else:
            self.failures.labels(device).inc()


class StateCollector:
    """Reads the state file on every scrape, so the exporter always shows the latest run."""

    def __init__(self, state_path: Path, clock: Callable[[], float] = time.time) -> None:
        self.state_path = state_path
        self.clock = clock

    def collect(self) -> Iterator[Metric]:
        try:
            state = read_state(self.state_path)
        except (OSError, ValueError):
            state = None  # missing or unreadable: report it through the age metric below

        age = float("inf") if state is None else max(0.0, self.clock() - state.get("updated", 0))
        yield GaugeMetricFamily(
            "lab_state_age_seconds",
            "Seconds since the backup state was written (+Inf if never)",
            value=age,
        )
        if state is None:
            return

        drift_events = CounterMetricFamily(
            "lab_drift_events", "Drift events seen (new or changed findings)", labels=["device"]
        )
        findings = GaugeMetricFamily(
            "lab_drift_findings",
            "Findings in the latest check, by severity",
            labels=["device", "severity"],
        )
        versions = CounterMetricFamily(
            "lab_backup_versions", "Config versions stored", labels=["device"]
        )
        errors = CounterMetricFamily(
            "lab_backup_errors", "Failed backup attempts", labels=["device"]
        )
        last_ok = GaugeMetricFamily(
            "lab_backup_last_success_timestamp_seconds",
            "Unix time of the last successful backup",
            labels=["device"],
        )
        for name, dev in sorted(state.get("devices", {}).items()):
            drift_events.add_metric([name], dev["drift_events"])
            versions.add_metric([name], dev["versions_stored"])
            errors.add_metric([name], dev["errors"])
            if dev["last_success"] is not None:
                last_ok.add_metric([name], dev["last_success"])
            for severity in SEVERITIES:
                findings.add_metric([name, severity], dev["findings"].get(severity, 0))
        yield drift_events
        yield findings
        yield versions
        yield errors
        yield last_ok


class IdsCollector:
    """Counts Suricata alerts from eve.json on every scrape."""

    def __init__(self, eve_path: Path, clock: Callable[[], float] = time.time) -> None:
        self.eve_path = eve_path
        self.clock = clock

    def collect(self) -> Iterator[Metric]:
        try:
            age = max(0.0, self.clock() - self.eve_path.stat().st_mtime)
        except OSError:
            age = float("inf")
        yield GaugeMetricFamily(
            "lab_ids_eve_age_seconds",
            "Seconds since Suricata last wrote eve.json (+Inf if missing)",
            value=age,
        )
        alerts = CounterMetricFamily(
            "lab_ids_alerts",
            "Suricata alerts by signature, severity, source and destination",
            labels=["signature", "sid", "severity", "src", "dst"],
        )
        counts = count_alerts(self.eve_path)
        for alert in sorted(counts, key=lambda a: (a.sid, a.src, a.dst)):
            labels = [alert.signature, alert.sid, alert.severity, alert.src, alert.dst]
            alerts.add_metric(labels, counts[alert])
        yield alerts


def build_registry(state_path: Path, eve_path: Path) -> tuple[CollectorRegistry, ProbeMetrics]:
    registry = CollectorRegistry()
    metrics = ProbeMetrics(registry)
    registry.register(StateCollector(state_path))
    registry.register(IdsCollector(eve_path))
    return registry, metrics
