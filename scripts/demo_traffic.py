"""Run harmless detection-test traffic from inside the lab. Host side (uses docker compose exec).

  python scripts/demo_traffic.py all
  python scripts/demo_traffic.py port-scan modbus-write

Each scenario lists the Suricata SIDs it should trigger (see lab/suricata/rules/lab.rules).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE = REPO_ROOT / "compose" / "docker-compose.yml"
TRAFFIC = "/opt/tools/traffic.py"


@dataclass(frozen=True)
class Step:
    service: str  # lab container that generates the traffic
    args: tuple[str, ...]  # arguments for lab/tools/traffic.py


@dataclass(frozen=True)
class Scenario:
    description: str
    steps: tuple[Step, ...]
    expected_sids: frozenset[int]


SCENARIOS: dict[str, Scenario] = {
    "unexpected-industrial": Scenario(
        "user PC tries to reach the PLC (router drops it, IDS records it)",
        (Step("user-pc", ("connect", "--host", "10.10.40.10", "--port", "502")),),
        frozenset({1000001}),
    ),
    "management-attempt": Scenario(
        "user PC tries SSH to the app server (blocked by the router)",
        (Step("user-pc", ("connect", "--host", "10.10.20.10", "--port", "22")),),
        frozenset({1000002}),
    ),
    "modbus-write": Scenario(
        "engineering workstation sends Modbus writes to the PLC (answered with exception)",
        (
            Step("eng-ws", ("modbus-write", "--host", "10.10.40.10", "--fc", "6")),
            Step("eng-ws", ("modbus-write", "--host", "10.10.40.10", "--fc", "16")),
        ),
        frozenset({1000003, 1000004}),
    ),
    "port-scan": Scenario(
        "user PC scans 60 ports on the app server (SYN burst)",
        (Step("user-pc", ("scan", "--host", "10.10.20.10", "--ports", "1-60")),),
        frozenset({1000005}),
    ),
}


def run_step(step: Step, compose: Path) -> int:
    cmd = [
        "docker", "compose", "-f", str(compose), "exec", "-T", step.service,
        "python", TRAFFIC, *step.args,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    output = (proc.stdout + proc.stderr).strip()
    print(f"  [{step.service}] {output}")
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harmless lab detection traffic")
    parser.add_argument("scenarios", nargs="+", choices=[*SCENARIOS, "all"])
    parser.add_argument("--compose-file", type=Path, default=COMPOSE)
    args = parser.parse_args(argv)

    names = list(SCENARIOS) if "all" in args.scenarios else args.scenarios
    failed = 0
    for name in names:
        scenario = SCENARIOS[name]
        print(f"{name}: {scenario.description}")
        for step in scenario.steps:
            if run_step(step, args.compose_file) != 0:
                failed += 1
    print("done" if not failed else f"{failed} step(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
