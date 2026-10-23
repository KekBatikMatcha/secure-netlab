"""Simulated Modbus/TCP PLC (function code 3 only). Standard library, no third-party deps.

Modbus/TCP frame = 7-byte MBAP header + PDU:
  MBAP: transaction id (2), protocol id (2, always 0), length (2), unit id (1)
  PDU : function code (1) + data
"""

from __future__ import annotations

import argparse
import socket
import socketserver
import struct

# Simulated holding registers for a fake process (values are arbitrary lab data).
DEFAULT_REGISTERS: list[int] = [1200, 480, 3, 25, 0, 0, 1, 42]

FC_READ_HOLDING = 3
EXC_ILLEGAL_FUNCTION = 1
EXC_ILLEGAL_ADDRESS = 2
EXC_ILLEGAL_VALUE = 3


def handle_pdu(pdu: bytes, registers: list[int]) -> bytes:
    """Return the response PDU for a request PDU."""
    fc = pdu[0]
    if fc != FC_READ_HOLDING:
        # Exception response: function code with the high bit set, plus exception code.
        return bytes([fc | 0x80, EXC_ILLEGAL_FUNCTION])
    if len(pdu) != 5:
        return bytes([fc | 0x80, EXC_ILLEGAL_VALUE])
    start, count = struct.unpack(">HH", pdu[1:5])
    if not 1 <= count <= 125:  # Modbus spec limit for a read
        return bytes([fc | 0x80, EXC_ILLEGAL_VALUE])
    if start + count > len(registers):
        return bytes([fc | 0x80, EXC_ILLEGAL_ADDRESS])
    values = registers[start : start + count]
    return bytes([fc, 2 * count]) + struct.pack(f">{count}H", *values)


def frame(transaction_id: int, unit_id: int, pdu: bytes) -> bytes:
    """Wrap a response PDU in an MBAP header. Length counts unit id + PDU."""
    return struct.pack(">HHHB", transaction_id, 0, len(pdu) + 1, unit_id) + pdu


def recv_exact(sock: socket.socket, n: int) -> bytes | None:
    """Read exactly n bytes, or return None if the peer closed the connection."""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


class ModbusHandler(socketserver.BaseRequestHandler):
    registers: list[int] = DEFAULT_REGISTERS

    def handle(self) -> None:
        while True:
            header = recv_exact(self.request, 7)
            if header is None:
                return
            tid, proto, length, unit = struct.unpack(">HHHB", header)
            # Reject anything that is not Modbus/TCP framing.
            if proto != 0 or not 2 <= length <= 254:
                return
            pdu = recv_exact(self.request, length - 1)
            if pdu is None:
                return
            self.request.sendall(frame(tid, unit, handle_pdu(pdu, self.registers)))


class ModbusServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(host: str, port: int, registers: list[int] | None = None) -> ModbusServer:
    """Create a server. Call serve_forever() or run it in a thread (used by tests)."""
    handler = type(
        "Handler", (ModbusHandler,), {"registers": registers or DEFAULT_REGISTERS}
    )
    return ModbusServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulated Modbus/TCP PLC")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=502)
    args = parser.parse_args()
    server = serve(args.host, args.port)
    print(f"modbus sim listening on {args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
