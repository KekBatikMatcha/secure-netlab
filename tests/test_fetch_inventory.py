"""Fetcher command construction and inventory parsing. The docker call is replaced by a fake."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from automation.fetch import DockerExecFetcher, FetchError
from automation.inventory import load_inventory, parse_inventory

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "compose" / "docker-compose.yml"
ROUTER = {"name": "router", "service": "router", "sections": {"firewall": "iptables-save"}}


class FakeRunner:
    """Records the argv of each call and returns scripted (returncode, stdout, stderr)."""

    def __init__(self, scripted: dict[str, tuple[int, str, str]]) -> None:
        self.scripted = scripted
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        command = argv[-1]
        code, out, err = self.scripted[command]
        return subprocess.CompletedProcess(argv, code, stdout=out, stderr=err)


def _device(data: dict[str, Any]):  # type: ignore[no-untyped-def]
    return parse_inventory({"devices": [data]})[0]


def test_docker_fetcher_runs_each_section_inside_its_service() -> None:
    runner = FakeRunner(
        {"iptables-save": (0, "*filter\nCOMMIT\n", ""), "netstat -tln": (0, "", "")}
    )
    device = _device(
        {
            "name": "router",
            "service": "router",
            "sections": {"firewall": "iptables-save", "listeners": "netstat -tln"},
        }
    )
    bundle = DockerExecFetcher(COMPOSE, runner=runner).fetch(device)

    assert runner.calls[0] == [
        "docker",
        "compose",
        "-f",
        str(COMPOSE),
        "exec",
        "-T",
        "router",
        "sh",
        "-c",
        "iptables-save",
    ]
    assert bundle.sections == {"firewall": "*filter\nCOMMIT\n", "listeners": ""}


def test_nonzero_exit_raises_and_no_partial_bundle_is_returned() -> None:
    runner = FakeRunner(
        {
            "iptables-save": (0, "*filter\n", ""),
            "netstat -tln": (1, "", "netstat: not found"),
        }
    )
    device = _device(
        {
            "name": "router",
            "service": "router",
            "sections": {"firewall": "iptables-save", "listeners": "netstat -tln"},
        }
    )
    with pytest.raises(FetchError, match="router/listeners: exit 1: netstat: not found"):
        DockerExecFetcher(COMPOSE, runner=runner).fetch(device)


def test_parse_inventory_accepts_valid_devices() -> None:
    (device,) = parse_inventory({"devices": [ROUTER]})
    assert device.name == "router"
    assert device.service == "router"
    assert device.sections == {"firewall": "iptables-save"}


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"service": "x", "sections": {"a": "b"}}, "needs a name"),
        ({"name": "x", "sections": {"a": "b"}}, "needs a service"),
        ({"name": "x", "service": "x", "sections": {}}, "needs at least one section"),
        ({"name": "x", "service": "x", "sections": {"a": 3}}, "must be strings"),
    ],
)
def test_parse_inventory_rejects_incomplete_devices(entry: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_inventory({"devices": [entry]})


def test_parse_inventory_rejects_duplicate_names() -> None:
    with pytest.raises(ValueError, match="duplicate device name: router"):
        parse_inventory({"devices": [ROUTER, ROUTER]})


def test_repo_inventory_is_valid_and_covers_the_router() -> None:
    devices = {d.name: d for d in load_inventory(ROOT / "inventory" / "devices.yaml")}
    assert "firewall" in devices["router"].sections
    assert "listeners" in devices["plc"].sections
