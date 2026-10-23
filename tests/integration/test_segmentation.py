"""Integration tests: run against the live Compose lab (make up). Requires Docker.

Each check runs a probe inside a lab container (docker compose exec), so the traffic
really crosses the router's iptables FORWARD chain.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose" / "docker-compose.yml"
SERVICES = ["router", "user-pc", "app-server", "eng-ws", "plc", "monitor", "prometheus", "grafana"]

# (source container, destination IP, port) that the segment rules must allow.
ALLOWED = [
    ("user-pc", "10.10.20.10", 8080),  # user -> server web app
    ("eng-ws", "10.10.20.10", 8080),  # management -> server web app
    ("app-server", "10.10.40.10", 502),  # server historian -> PLC
    ("eng-ws", "10.10.40.10", 502),  # management -> PLC
]

# (source, destination IP, port) that must be dropped. A drop shows up as a connect timeout;
# an allowed-but-closed port would be refused instead, so "timed out" proves the policy did it.
BLOCKED = [
    ("user-pc", "10.10.30.10", 8080),  # user -> management
    ("user-pc", "10.10.40.10", 502),  # user -> industrial (Modbus)
    ("user-pc", "10.10.20.10", 502),  # user -> server, port not allowed
    ("app-server", "10.10.30.10", 8080),  # server -> management
    ("eng-ws", "10.10.10.10", 8080),  # management -> user
    ("plc", "10.10.20.10", 8080),  # industrial -> server (no egress)
    ("plc", "10.10.10.10", 8080),  # industrial -> user (no egress)
]


def _exec(service: str, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "compose", "-f", str(COMPOSE), "exec", "-T", service, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _tcp(src: str, host: str, port: int) -> tuple[bool, str]:
    result = _exec(src, "python", "/opt/tools/probe.py", "tcp", host, str(port), "--timeout", "2")
    return result.returncode == 0, (result.stdout + result.stderr).strip()


@pytest.fixture(scope="module", autouse=True)
def lab_running() -> None:
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "ps", "--status", "running", "--services"],
        capture_output=True,
        text=True,
        check=False,
    )
    running = set(result.stdout.split())
    missing = set(SERVICES) - running
    if missing:
        pytest.fail(f"lab not running, missing: {sorted(missing)}. Run `make up` first.")


def test_router_default_policy_is_drop() -> None:
    result = _exec("router", "iptables", "-S", "FORWARD")
    assert "-P FORWARD DROP" in result.stdout


@pytest.mark.parametrize(("src", "dst", "port"), ALLOWED)
def test_allowed_flow_is_forwarded(src: str, dst: str, port: int) -> None:
    ok, output = _tcp(src, dst, port)
    assert ok, f"{src} -> {dst}:{port} should be allowed: {output}"


@pytest.mark.parametrize(("src", "dst", "port"), BLOCKED)
def test_blocked_flow_is_dropped(src: str, dst: str, port: int) -> None:
    ok, output = _tcp(src, dst, port)
    assert not ok, f"{src} -> {dst}:{port} should be blocked: {output}"
    assert "timed out" in output, f"expected a DROP (timeout), got: {output}"


def test_modbus_read_from_engineering_workstation() -> None:
    # Full application-layer check: read the 8 simulated holding registers from the PLC.
    result = _exec(
        "eng-ws", "python", "/opt/tools/probe.py", "modbus", "10.10.40.10", "--count", "8"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["1200", "480", "3", "25", "0", "0", "1", "42"]
