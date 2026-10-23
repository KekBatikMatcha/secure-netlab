"""TCP connect probes: is the service up, and how long does the handshake take.

A TCP handshake is a cheap, protocol-independent check. It works for the web app (8080) and the
Modbus PLC (502) without any application logic.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Connector = Callable[..., Any]  # socket.create_connection-compatible


@dataclass(frozen=True)
class Target:
    name: str
    host: str
    port: int


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    seconds: float  # handshake time on success, time spent before failing otherwise
    error: str = ""


def probe(
    target: Target,
    timeout: float = 2.0,
    connect: Connector = socket.create_connection,
    clock: Callable[[], float] = time.perf_counter,
) -> ProbeResult:
    start = clock()
    try:
        sock = connect((target.host, target.port), timeout=timeout)
    except OSError as exc:  # timeout (dropped by firewall), refused, or unreachable
        return ProbeResult(ok=False, seconds=clock() - start, error=str(exc))
    elapsed = clock() - start
    sock.close()
    return ProbeResult(ok=True, seconds=elapsed)
