"""Command line: python -m automation <command>

  check                 fetch all devices, store changed versions, report drift (exit 1 on drift)
  run --every SECONDS   repeat `check` on a schedule (--cycles N to stop after N runs)
  baseline DEVICE       fetch a device and accept its current config as the baseline

Exit codes for check: 0 clean, 1 drift found, 2 a device could not be collected.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from automation.backup import CycleResult, run_cycle, run_scheduled
from automation.fetch import DockerExecFetcher
from automation.inventory import Device, load_inventory
from automation.store import BackupStore, BaselineStore

REPO_ROOT = Path(__file__).resolve().parents[1]


def _print_results(results: list[CycleResult]) -> None:
    for result in results:
        if result.status == "error":
            print(f"ERROR {result.device}: {result.error}")
            continue
        print(f"{result.device}: {result.status}")
        if result.report is not None:
            print(result.report.to_text())
        else:
            print(f"  (no baseline for {result.device}; run `baseline {result.device}`)")


def exit_code(results: list[CycleResult]) -> int:
    if any(r.status == "error" for r in results):
        return 2
    if any(r.report is not None and r.report.has_drift for r in results):
        return 1
    return 0


def _select(devices: list[Device], name: str | None) -> list[Device]:
    if name is None:
        return devices
    selected = [d for d in devices if d.name == name]
    if not selected:
        raise SystemExit(f"unknown device: {name}")
    return selected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="automation", description=__doc__.split("\n")[0])
    parser.add_argument("--inventory", type=Path, default=REPO_ROOT / "inventory" / "devices.yaml")
    parser.add_argument(
        "--compose-file", type=Path, default=REPO_ROOT / "compose" / "docker-compose.yml"
    )
    parser.add_argument("--backups", type=Path, default=REPO_ROOT / "backups")
    parser.add_argument("--golden", type=Path, default=REPO_ROOT / "golden")

    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check", help="fetch, store, and compare with baseline")
    p_check.add_argument("--device", help="only this device")

    p_run = sub.add_parser("run", help="repeat check on a schedule")
    p_run.add_argument("--every", type=float, required=True, help="seconds between cycles")
    p_run.add_argument("--cycles", type=int, default=None, help="stop after N cycles")
    p_run.add_argument("--device", help="only this device")

    p_base = sub.add_parser("baseline", help="accept a device's current config as baseline")
    p_base.add_argument("device")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    devices = load_inventory(args.inventory)
    fetcher = DockerExecFetcher(args.compose_file)
    store = BackupStore(args.backups)
    baseline = BaselineStore(args.golden)

    if args.command == "baseline":
        (device,) = _select(devices, args.device)
        bundle = fetcher.fetch(device)
        path = baseline.accept(device.name, bundle)
        print(f"baseline for {device.name} written to {path}")
        return 0

    selected = _select(devices, args.device)
    if args.command == "check":
        results = run_cycle(selected, fetcher, store, baseline)
        _print_results(results)
        return exit_code(results)

    # run
    last: list[CycleResult] = []

    def remember(results: list[CycleResult]) -> None:
        nonlocal last
        last = results
        _print_results(results)
        print("---")

    run_scheduled(
        selected,
        fetcher,
        store,
        baseline,
        every=args.every,
        cycles=args.cycles,
        on_results=remember,
    )
    return exit_code(last)

