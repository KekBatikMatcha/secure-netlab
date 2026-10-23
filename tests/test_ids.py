"""Suricata eve.json parsing and the IDS collector. Uses tests/fixtures/eve_sample.json."""

from __future__ import annotations

from pathlib import Path

import pytest

from monitor.exporter import IdsCollector
from monitor.ids import IdsAlert, count_alerts, parse_alert

FIXTURES = Path(__file__).parent / "fixtures"
EVE = FIXTURES / "eve_sample.json"


def test_parse_alert_maps_fields_and_severity() -> None:
    line = (
        '{"event_type":"alert","src_ip":"10.10.10.10","dest_ip":"10.10.40.10",'
        '"alert":{"signature_id":1000001,"signature":"LAB x","severity":1}}'
    )
    assert parse_alert(line) == IdsAlert(
        signature="LAB x", sid="1000001", severity="high", src="10.10.10.10", dst="10.10.40.10"
    )


@pytest.mark.parametrize(
    "line",
    [
        '{"event_type":"flow","src_ip":"10.10.10.10"}',  # not an alert
        '{"event_type":"stats","stats":{}}',
        "not json at all",
        '["a", "list"]',
        '{"event_type":"alert"}',  # alert event without the alert object
    ],
)
def test_parse_alert_ignores_other_events_and_bad_lines(line: str) -> None:
    assert parse_alert(line) is None


def test_unknown_severity_is_labelled_unknown_not_dropped() -> None:
    line = '{"event_type":"alert","alert":{"signature_id":9,"signature":"s","severity":"??"}}'
    alert = parse_alert(line)
    assert alert is not None and alert.severity == "unknown"


def test_count_alerts_groups_by_signature_src_and_dst() -> None:
    counts = count_alerts(EVE)
    industrial = IdsAlert(
        "LAB unexpected connection attempt into industrial segment",
        "1000001",
        "high",
        "10.10.10.10",
        "10.10.40.10",
    )
    assert counts[industrial] == 2
    assert sum(counts.values()) == 3  # the flow, stats and malformed lines are not counted


def test_count_alerts_missing_file_is_empty(tmp_path: Path) -> None:
    assert count_alerts(tmp_path / "eve.json") == {}


def test_ids_collector_exports_counts_and_age(tmp_path: Path) -> None:
    collector = IdsCollector(EVE, clock=lambda: EVE.stat().st_mtime + 42)
    families = {f.name: f for f in collector.collect()}
    assert families["lab_ids_eve_age_seconds"].samples[0].value == pytest.approx(42)
    alerts = {tuple(s.labels.values()): s.value for s in families["lab_ids_alerts"].samples}
    assert alerts[
        (
            "LAB unexpected connection attempt into industrial segment",
            "1000001",
            "high",
            "10.10.10.10",
            "10.10.40.10",
        )
    ] == 2


def test_ids_collector_reports_infinite_age_when_eve_is_missing(tmp_path: Path) -> None:
    families = {f.name: f for f in IdsCollector(tmp_path / "eve.json").collect()}
    assert families["lab_ids_eve_age_seconds"].samples[0].value == float("inf")
    assert families["lab_ids_alerts"].samples == []
