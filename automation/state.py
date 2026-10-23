"""Persisted backup state, written by `check`/`run` and read by the Prometheus exporter.

The file holds cumulative counters (versions, errors, drift events) so they keep counting across
CLI restarts. Prometheus rate() works best with counters that never reset.

Schema (reports/state.json):
  {"updated": <unix seconds>,
   "devices": {"<name>": {"last_success": <unix or null>, "versions_stored": int,
                          "errors": int, "drift_events": int,
                          "last_drift": "<fingerprint or empty>",
                          "findings": {"high": int, "medium": int, "low": int}}}}
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

SEVERITIES = ("high", "medium", "low")


def _empty_device() -> dict[str, Any]:
    return {
        "last_success": None,
        "versions_stored": 0,
        "errors": 0,
        "drift_events": 0,
        "last_drift": "",
        "findings": {s: 0 for s in SEVERITIES},
    }


def read_state(path: Path) -> dict[str, Any] | None:
    """Return the parsed state, or None if the file does not exist yet."""
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fingerprint(findings: Sequence[tuple[str, str]]) -> str:
    """Stable id for a set of findings. A new fingerprint means a new drift event."""
    if not findings:
        return ""
    joined = "\n".join(sorted(f"{kind}|{detail}" for kind, detail in findings))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def apply_results(
    state: dict[str, Any] | None, results: Sequence[Any], now: float
) -> dict[str, Any]:
    """Fold one cycle's results into the state. `results` are backup.CycleResult objects.

    Kept free of I/O and of the backup module's imports so it is easy to test.
    """
    new: dict[str, Any] = state if state is not None else {"devices": {}}
    new["updated"] = now
    devices: dict[str, Any] = new.setdefault("devices", {})

    for result in results:
        dev = devices.setdefault(result.device, _empty_device())
        if result.status == "error":
            dev["errors"] += 1
            continue  # keep last known findings and last success time

        dev["last_success"] = now
        if result.status == "stored":
            dev["versions_stored"] += 1
        report = result.report
        if report is None:
            continue  # no baseline yet, so no drift to record

        counts = {s: 0 for s in SEVERITIES}
        for finding in report.findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        dev["findings"] = counts

        # Count an event when drift appears or changes. Persistent drift is not re-counted.
        fp = fingerprint([(f.kind, f.detail) for f in report.findings])
        if fp and fp != dev.get("last_drift", ""):
            dev["drift_events"] += 1
        dev["last_drift"] = fp
    return new


def write_state(path: Path, state: dict[str, Any]) -> None:
    """Write atomically so the exporter never reads a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def update_state(path: Path, results: Sequence[Any], now: float) -> dict[str, Any]:
    state = apply_results(read_state(path), results, now)
    write_state(path, state)
    return state
