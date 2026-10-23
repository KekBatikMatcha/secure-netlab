"""Parse Suricata eve.json into IDS alert counts for Prometheus.

eve.json is one JSON object per line. Only "event_type": "alert" lines matter here; flow, stats and
protocol events are skipped. Counts are recomputed from the file on each scrape. That keeps them
correct across restarts, at the cost of rereading the file (fine for a lab-sized log).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# Suricata's alert.severity: 1 = high, 2 = medium, 3 = low (set by the rule's priority keyword).
SEVERITY_NAMES = {1: "high", 2: "medium", 3: "low"}


@dataclass(frozen=True)
class IdsAlert:
    signature: str
    sid: str
    severity: str
    src: str
    dst: str


def parse_alert(line: str) -> IdsAlert | None:
    """Return the alert on this eve.json line, or None for any other event or malformed JSON."""
    try:
        event = json.loads(line)
    except ValueError:
        return None
    if not isinstance(event, dict) or event.get("event_type") != "alert":
        return None
    alert = event.get("alert")
    if not isinstance(alert, dict):
        return None
    try:
        severity = SEVERITY_NAMES.get(int(alert.get("severity", 0)), "unknown")
    except (TypeError, ValueError):
        severity = "unknown"
    return IdsAlert(
        signature=str(alert.get("signature", "")),
        sid=str(alert.get("signature_id", "")),
        severity=severity,
        src=str(event.get("src_ip", "")),
        dst=str(event.get("dest_ip", "")),
    )


def count_alerts(path: Path) -> Counter[IdsAlert]:
    """Count alerts per (signature, sid, severity, src, dst). A missing file counts as empty."""
    counts: Counter[IdsAlert] = Counter()
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                alert = parse_alert(line)
                if alert is not None:
                    counts[alert] += 1
    except OSError:
        return Counter()
    return counts
