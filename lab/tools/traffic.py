"""Harmless test traffic for detection demos. Runs inside lab containers (/opt/tools/traffic.py).

Safety rules, enforced in code:
  * targets must be IP addresses inside the lab address space 10.10.0.0/16 (anything else raises)
  * scans are bounded (MAX_PORTS) and use short timeouts
  * the only payloads are two Modbus write requests. The PLC simulator does not implement writes,
    so it answers with an exception and changes nothing.

  python traffic.py connect --host 10.10.40.10 --port 502
  python traffic.py scan --host 10.10.20.10 --ports 1-60
  python traffic.py modbus-write --host 10.10.40.10 --fc 6
"""

from __future__ import annotations

import argparse
import ipaddress
import socket
import struct
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

LAB_NETWORK = ipaddress.ip_network("10.10.0.0/16")
MAX_PORTS = 100
CONNECT_TIMEOUT = 1.0


def ensure_lab_target(host: str) -> str:
    """Return the host if it is a lab IP literal. Raise ValueError for anything else."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError(f"target must be an IP address, got {host!r}") from exc
    if address not in LAB_NETWORK:
        raise ValueError(f"refusing non-lab target {host}; allowed range is {LAB_NETWORK}")
    return host


def parse_ports(spec: str) -> list[int]:
    """Parse "22,80,1000-1010" into a sorted list. Enforces the MAX_PORTS limit."""
    ports: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            low_s, high_s = part.split("-", 1)
            low, high = int(low_s), int(high_s)
        else:
            low = high = int(part)
        if not (1 <= low <= high <= 65535):
            raise ValueError(f"invalid port range {part!r}")
        ports.update(range(low, high + 1))
    if not ports:
        raise ValueError("no ports given")
    if len(ports) > MAX_PORTS:
        raise ValueError(f"at most {MAX_PORTS} ports per scan, got {len(ports)}")
    return sorted(ports)


def connect_once(host: str, port: int, timeout: float = CONNECT_TIMEOUT) -> bool:
    """One TCP connection attempt. Returns True if the handshake completed."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def scan(
    host: str,
    ports: list[int],
    connect: Callable[[str, int], bool] = connect_once,
    workers: int = 16,
) -> dict[int, bool]:
    """Connection attempts to many ports, a few at a time. Produces a SYN burst from one source."""
    ensure_lab_target(host)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(lambda port: connect(host, port), ports)
        return dict(zip(ports, results, strict=True))


def modbus_write_request(fc: int, start: int = 0, value: int = 1) -> bytes:
    """Build a Modbus/TCP write request. FC 6 writes one register; FC 16 writes one as a block."""
    if fc == 6:
        pdu = struct.pack(">BHH", 6, start, value)
    elif fc == 16:
        pdu = struct.pack(">BHHBH", 16, start, 1, 2, value)
    else:
        raise ValueError("only function codes 6 and 16 are supported")
    # MBAP header: transaction id, protocol id (0), length (unit id + PDU), unit id
    return struct.pack(">HHHB", 1, 0, len(pdu) + 1, 1) + pdu


def modbus_write(host: str, fc: int, timeout: float = 3.0) -> str:
    """Send one write request and return the PLC's reply: "exception N" or "ok"."""
    ensure_lab_target(host)
    with socket.create_connection((host, 502), timeout=timeout) as sock:
        sock.sendall(modbus_write_request(fc))
        header = sock.recv(7)
        if len(header) < 7:
            return "no reply"
        _, _, length, _ = struct.unpack(">HHHB", header)
        body = sock.recv(length - 1)
    if body and body[0] & 0x80:
        return f"exception {body[1]}"
    return "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lab-only detection test traffic")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_connect = sub.add_parser("connect", help="one TCP connection attempt")
    p_connect.add_argument("--host", required=True)
    p_connect.add_argument("--port", type=int, required=True)

    p_scan = sub.add_parser("scan", help="connection attempts to a list of ports")
    p_scan.add_argument("--host", required=True)
    p_scan.add_argument("--ports", required=True, help='e.g. "1-60" or "22,502,8080"')

    p_mb = sub.add_parser("modbus-write", help="one Modbus write request (answered with exception)")
    p_mb.add_argument("--host", required=True)
    p_mb.add_argument("--fc", type=int, choices=[6, 16], default=6)

    args = parser.parse_args(argv)
    try:
        if args.cmd == "connect":
            ensure_lab_target(args.host)
            ok = connect_once(args.host, args.port)
            print(f"connect {args.host}:{args.port} -> {'open' if ok else 'no answer'}")
        elif args.cmd == "scan":
            ports = parse_ports(args.ports)
            results = scan(args.host, ports)
            open_ports = [p for p, ok in results.items() if ok]
            print(f"scan {args.host}: {len(ports)} ports attempted, open {open_ports or 'none'}")
        else:
            print(f"modbus fc{args.fc} {args.host}: {modbus_write(args.host, args.fc)}")
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
