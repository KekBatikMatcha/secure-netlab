"""Monitor service: probes lab targets on an interval and serves Prometheus metrics on :9101.

  python -m monitor.app --targets monitor/targets.yaml --state reports/state.json
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import yaml
from prometheus_client import start_http_server

from monitor.exporter import ProbeMetrics, build_registry
from monitor.probe import ProbeResult, Target, probe


def load_targets(path: Path) -> list[Target]:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("targets"), list):
        raise ValueError("targets file must have a 'targets' list")
    targets = []
    for entry in data["targets"]:
        if not isinstance(entry, dict) or not all(k in entry for k in ("name", "host", "port")):
            raise ValueError(f"target needs name, host and port: {entry!r}")
        targets.append(Target(str(entry["name"]), str(entry["host"]), int(entry["port"])))
    return targets


def probe_loop(
    targets: Sequence[Target],
    metrics: ProbeMetrics,
    probe_fn: Callable[[Target], ProbeResult],
    *,
    interval: float,
    sleep: Callable[[float], None] = time.sleep,
    cycles: int | None = None,
) -> None:
    """Probe every target once per cycle. cycles=None runs until the process is stopped."""
    done = 0
    while cycles is None or done < cycles:
        for target in targets:
            metrics.record(target.name, probe_fn(target))
        done += 1
        if cycles is None or done < cycles:
            sleep(interval)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lab uptime/latency monitor (Prometheus)")
    parser.add_argument("--targets", type=Path, default=Path("monitor/targets.yaml"))
    parser.add_argument("--state", type=Path, default=Path("reports/state.json"))
    parser.add_argument("--eve", type=Path, default=Path("reports/suricata/eve.json"))
    parser.add_argument("--port", type=int, default=9101)
    parser.add_argument("--interval", type=float, default=15.0)
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args(argv)

    targets = load_targets(args.targets)
    registry, metrics = build_registry(args.state, args.eve)
    start_http_server(args.port, registry=registry)
    print(f"monitor: {len(targets)} targets, metrics on :{args.port}", flush=True)
    probe_loop(
        targets,
        metrics,
        lambda t: probe(t, timeout=args.timeout),
        interval=args.interval,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
