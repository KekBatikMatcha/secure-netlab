"""Test probe run inside lab containers (via `docker compose exec`).

  python probe.py tcp HOST PORT [--timeout 2]   exit 0 if TCP connect succeeds, else 1
  python probe.py modbus HOST [--start 0 --count 4]   read holding registers, print them

Standard library only. Mounted read-only into every lab endpoint at /opt/tools.
"""

from __future__ import annotations

import argparse
import socket
import struct
import sys


def tcp_probe(host: str, port: int, timeout: float) -> int:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            print(f"OPEN {host}:{port}")
            return 0
    except OSError as exc:  # timeout (dropped by firewall) or refused
        print(f"CLOSED {host}:{port} ({exc})")
        return 1


def modbus_read(host: str, start: int, count: int, timeout: float) -> int:
    # Request PDU: function 3, start address, quantity. MBAP length = unit id + PDU = 6.
    request = struct.pack(">HHHB", 1, 0, 6, 1) + struct.pack(">BHH", 3, start, count)
    with socket.create_connection((host, 502), timeout=timeout) as sock:
        sock.sendall(request)
        header = sock.recv(7)
        if len(header) < 7:
            print("short MBAP header", file=sys.stderr)
            return 1
        _, _, length, _ = struct.unpack(">HHHB", header)
        body = b""
        while len(body) < length - 1:
            chunk = sock.recv(length - 1 - len(body))
            if not chunk:
                break
            body += chunk
    fc = body[0]
    if fc != 3:
        print(f"modbus exception: function {fc:#x}, code {body[1]}", file=sys.stderr)
        return 1
    values = struct.unpack(f">{count}H", body[2 : 2 + 2 * count])
    print(" ".join(str(v) for v in values))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Lab test probe")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_tcp = sub.add_parser("tcp")
    p_tcp.add_argument("host")
    p_tcp.add_argument("port", type=int)
    p_tcp.add_argument("--timeout", type=float, default=2.0)

    p_mb = sub.add_parser("modbus")
    p_mb.add_argument("host")
    p_mb.add_argument("--start", type=int, default=0)
    p_mb.add_argument("--count", type=int, default=4)
    p_mb.add_argument("--timeout", type=float, default=3.0)

    args = parser.parse_args()
    if args.cmd == "tcp":
        return tcp_probe(args.host, args.port, args.timeout)
    return modbus_read(args.host, args.start, args.count, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
