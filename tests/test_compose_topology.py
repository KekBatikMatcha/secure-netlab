"""Static checks on compose/docker-compose.yml. No Docker needed."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "compose" / "docker-compose.yml"

# segment name -> subnet (must match lab/router/rules.sh and docs/topology.md)
SEGMENTS = {
    "user": "10.10.10.0/24",
    "server": "10.10.20.0/24",
    "management": "10.10.30.0/24",
    "industrial": "10.10.40.0/24",
}
ROUTER_IP = {
    seg: str(ipaddress.ip_network(net).network_address + 1) for seg, net in SEGMENTS.items()
}
ENDPOINTS = {
    "user-pc": ("user", "10.10.10.10"),
    "app-server": ("server", "10.10.20.10"),
    "eng-ws": ("management", "10.10.30.10"),
    "plc": ("industrial", "10.10.40.10"),
    "monitor": ("management", "10.10.30.20"),
}


def _load() -> dict[str, Any]:
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_four_segments_with_expected_subnets() -> None:
    networks = _load()["networks"]
    assert set(networks) == set(SEGMENTS)
    for name, subnet in SEGMENTS.items():
        assert networks[name]["ipam"]["config"][0]["subnet"] == subnet


def test_no_ports_published_to_host() -> None:
    # Lab is localhost-only: any published port must be bound to 127.0.0.1.
    for name, svc in _load()["services"].items():
        for mapping in svc.get("ports", []):
            assert str(mapping).startswith("127.0.0.1:"), f"{name} exposes {mapping}"


def test_every_endpoint_on_exactly_one_segment_with_static_ip() -> None:
    services = _load()["services"]
    for name, (segment, ip) in ENDPOINTS.items():
        nets = services[name]["networks"]
        assert list(nets) == [segment], f"{name} must sit on {segment} only"
        assert nets[segment]["ipv4_address"] == ip
        assert ipaddress.ip_address(ip) in ipaddress.ip_network(SEGMENTS[segment])


def test_router_on_all_segments_at_dot_one_with_forwarding() -> None:
    router = _load()["services"]["router"]
    for seg, ip in ROUTER_IP.items():
        assert router["networks"][seg]["ipv4_address"] == ip
    assert router["sysctls"]["net.ipv4.ip_forward"] == "1"


def test_endpoints_default_route_points_at_their_segment_router() -> None:
    # Isolation depends on this: an endpoint can only leave its segment through the router.
    services = _load()["services"]
    for name, (segment, _) in ENDPOINTS.items():
        command = services[name]["command"]
        assert f"ip route replace default via {ROUTER_IP[segment]}" in command, name
