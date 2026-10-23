"""Unit tests for the simulated Modbus/TCP PLC. No Docker needed."""

from __future__ import annotations

import socket
import struct
import threading

import modbus_server as mb


def test_read_holding_registers_returns_values() -> None:
    # FC3, start 0, count 2 -> byte count 4, then two big-endian registers.
    pdu = struct.pack(">BHH", 3, 0, 2)
    assert mb.handle_pdu(pdu, [1200, 480]) == bytes([3, 4]) + struct.pack(">HH", 1200, 480)


def test_unsupported_function_code_gets_illegal_function_exception() -> None:
    # FC6 (write single register) is not implemented: exception 0x86, code 1.
    assert mb.handle_pdu(struct.pack(">BHH", 6, 0, 1), [0]) == bytes([0x86, 1])


def test_out_of_range_address_gets_illegal_address_exception() -> None:
    pdu = struct.pack(">BHH", 3, 6, 4)  # registers 6..9 but only 8 exist
    assert mb.handle_pdu(pdu, mb.DEFAULT_REGISTERS) == bytes([0x83, 2])


def test_zero_count_gets_illegal_value_exception() -> None:
    assert mb.handle_pdu(struct.pack(">BHH", 3, 0, 0), [0]) == bytes([0x83, 3])


def test_frame_length_counts_unit_id_and_pdu() -> None:
    pdu = bytes([3, 2, 0, 1])
    header = mb.frame(transaction_id=7, unit_id=1, pdu=pdu)
    tid, proto, length, unit = struct.unpack(">HHHB", header[:7])
    assert (tid, proto, length, unit) == (7, 0, len(pdu) + 1, 1)
    assert header[7:] == pdu


def _read_exact(sock: socket.socket, n: int) -> bytes:
    # MSG_WAITALL is not supported on Windows, so loop until n bytes arrive.
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        assert chunk, "connection closed early"
        buf += chunk
    return buf


def test_server_answers_a_real_request_over_tcp() -> None:
    server = mb.serve("127.0.0.1", 0, registers=[11, 22, 33])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        request = struct.pack(">HHHB", 1, 0, 6, 1) + struct.pack(">BHH", 3, 0, 3)
        with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
            sock.sendall(request)
            header = _read_exact(sock, 7)
            _, _, length, _ = struct.unpack(">HHHB", header)
            body = _read_exact(sock, length - 1)
        assert body == bytes([3, 6]) + struct.pack(">HHH", 11, 22, 33)
    finally:
        server.shutdown()
        server.server_close()
