"""One-command demo: start the lab, back up and check the devices, then run detection traffic.

  make demo                  (Linux/macOS, or Windows with make)
  python scripts/demo.py     (any OS; needs Docker and `pip install -r requirements-dev.txt`)

Drift found by the check is expected on a modified lab, so exit code 1 from the check does not stop
the demo. Any other failure does.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE = REPO_ROOT / "compose" / "docker-compose.yml"
GRAFANA_URL = "http://127.0.0.1:3000/d/lab-overview"
PROMETHEUS_URL = "http://127.0.0.1:9090/alerts"


def plan(python: str, compose: Path = COMPOSE) -> list[tuple[str, list[str], frozenset[int]]]:
    """Steps as (description, argv, exit codes that do not stop the demo)."""
    return [
        (
            "Starting the lab (first run builds the images)",
            ["docker", "compose", "-f", str(compose), "up", "-d", "--build", "--wait"],
            frozenset({0}),
        ),
        (
            "Backing up the devices and comparing with the baselines",
            [python, "-m", "automation", "check"],
            frozenset({0, 1}),
        ),
        (
            "Running harmless detection traffic (alerts appear in Grafana and Prometheus)",
            [python, str(REPO_ROOT / "scripts" / "demo_traffic.py"), "all"],
            frozenset({0}),
        ),
    ]


def main() -> int:
    for description, argv, ok_codes in plan(sys.executable):
        print(f"==> {description}", flush=True)
        result = subprocess.run(argv, cwd=REPO_ROOT, check=False)
        if result.returncode not in ok_codes:
            print(f"step failed with exit code {result.returncode}", file=sys.stderr)
            return result.returncode
    print()
    print("Demo ready.")
    print(f"  Grafana dashboard: {GRAFANA_URL}  (anonymous viewer, localhost only)")
    print(f"  Prometheus alerts: {PROMETHEUS_URL}")
    print("  Stop the lab with: make down")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
