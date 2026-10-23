"""Lab traffic tool: safety guard, bounds and request bytes. Fake connectors, no network."""

from __future__ import annotations

import struct

import demo_traffic
import pytest
import traffic


@pytest.mark.parametrize("host", ["10.10.40.10", "10.10.0.1", "10.10.255.254"])
def test_lab_addresses_are_accepted(host: str) -> None:
    assert traffic.ensure_lab_target(host) == host


@pytest.mark.parametrize(
    "host",
    ["8.8.8.8", "127.0.0.1", "10.11.0.1", "192.168.1.1", "0.0.0.0", "plc", "example.com", ""],
)
def test_non_lab_targets_are_refused(host: str) -> None:
    with pytest.raises(ValueError):
        traffic.ensure_lab_target(host)


def test_scan_refuses_non_lab_target_before_connecting() -> None:
    calls: list[tuple[str, int]] = []
    with pytest.raises(ValueError):
        traffic.scan("8.8.8.8", [80], connect=lambda h, p: calls.append((h, p)) or True)
    assert calls == []


def test_parse_ports_accepts_ranges_and_lists() -> None:
    assert traffic.parse_ports("22,80,1000-1003") == [22, 80, 1000, 1001, 1002, 1003]


@pytest.mark.parametrize("spec", ["0", "70000", "40-20", "", "1-200"])
def test_parse_ports_rejects_bad_or_oversized_specs(spec: str) -> None:
    with pytest.raises(ValueError):
        traffic.parse_ports(spec)


def test_scan_reports_result_per_port_using_the_connector() -> None:
    open_ports = {8080}
    results = traffic.scan(
        "10.10.20.10",
        [22, 8080, 9000],
        connect=lambda host, port: port in open_ports,
        workers=2,
    )
    assert results == {22: False, 8080: True, 9000: False}


def test_fc6_request_bytes() -> None:
    frame = traffic.modbus_write_request(6, start=0, value=1)
    tid, proto, length, unit = struct.unpack(">HHHB", frame[:7])
    assert (tid, proto, length, unit) == (1, 0, 6, 1)
    assert frame[7:] == bytes([6, 0, 0, 0, 1])


def test_fc16_request_bytes() -> None:
    frame = traffic.modbus_write_request(16, start=5, value=7)
    _, _, length, _ = struct.unpack(">HHHB", frame[:7])
    assert frame[7] == 16
    assert length == len(frame) - 6  # length counts unit id + PDU


def test_only_function_codes_6_and_16_can_be_built() -> None:
    # Keeps the demo harmless: no read or diagnostic traffic can be generated from here.
    with pytest.raises(ValueError):
        traffic.modbus_write_request(3)


def test_every_demo_target_is_inside_the_lab() -> None:
    # Static guard on the demo scenarios: every --host argument must pass the lab check.
    for scenario in demo_traffic.SCENARIOS.values():
        for step in scenario.steps:
            if "--host" in step.args:
                host = step.args[step.args.index("--host") + 1]
                traffic.ensure_lab_target(host)


def test_demo_scenarios_are_bounded() -> None:
    for name, scenario in demo_traffic.SCENARIOS.items():
        assert scenario.steps, name
        assert len(scenario.steps) <= 4, name
