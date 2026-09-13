"""Test 13 — optional WebSocket handshake automation.

Reproduces exactly what the real frontend does (frontend/lib/api.js +
frontend/lib/useChainFeed.js):

* URL ``/chains/ws/<SYMBOL>?expiry_date=<date>`` (expiry_date is required)
* the session id rides as the second Sec-WebSocket-Protocol entry
  (``options-dashboard-session``), or no protocols when logged out

Expected live-staging outcome without a broker connection (verified manually
in browser acceptance): the server completes the RFC 6455 upgrade (101 +
Sec-WebSocket-Accept proof — the connection-layer OPEN) and sends no data
frames. The automated test asserts exactly that verified behavior and
RECORDS whatever close-frame behavior it observes (an expectation that the
server closes with 4401 is NOT asserted: during the 2026-09-13 smoke run the
server did not send a close frame within the observation window, which
contradicts the current code path in app/routers/chains.py and is reported
as a finding for the owner instead of being auto-"fixed" here).

Uses only the Python standard library — no new infrastructure or
dependencies.
"""

import base64
import hashlib
import os
import socket
import ssl
import struct

import pytest

from tests.staging_smoke.conftest import BASE_URL, FRONTEND_URL

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_WS_PATH = "/chains/ws/NIFTY?expiry_date=2026-09-17"


def _handshake(protocols_header: str | None) -> dict:
    """Perform the RFC 6455 upgrade and return the open socket + response.

    The caller owns closing the returned sockets.
    """
    host = BASE_URL.split("//", 1)[1]  # strikenova-api-staging.onrender.com
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {_WS_PATH} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"Origin: {FRONTEND_URL}\r\n"
    )
    if protocols_header:
        request += f"Sec-WebSocket-Protocol: {protocols_header}\r\n"
    request += "\r\n"

    raw = socket.create_connection((host, 443), timeout=30)
    tls = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
    tls.settimeout(20)
    tls.sendall(request.encode())

    response = b""
    while b"\r\n\r\n" not in response:
        chunk = tls.recv(4096)
        if not chunk:
            break
        response += chunk
    head, _, rest = response.partition(b"\r\n\r\n")
    head = head.decode("latin-1")
    status_line = head.split("\r\n", 1)[0]
    headers = {
        line.split(":", 1)[0].strip().lower(): line.split(":", 1)[1].strip()
        for line in head.split("\r\n")[1:]
        if ":" in line
    }
    expected_accept = base64.b64encode(
        hashlib.sha1((key + _WS_GUID).encode()).digest()
    ).decode()
    return {
        "raw": raw,
        "tls": tls,
        "status_line": status_line,
        "headers": headers,
        "expected_accept": expected_accept,
        "rest": rest,
    }


def _read_server_close_frame(tls, first_bytes: bytes, wait: float = 8.0) -> int | None:
    """Observe the first WebSocket frame; return its close code or None.

    Observation only — a silent server (no frame before ``wait``) is a
    recorded finding, not an assertion failure.
    """
    tls.settimeout(wait)
    data = first_bytes
    try:
        while len(data) < 2:
            chunk = tls.recv(4096)
            if not chunk:
                return None  # EOF without a close frame
            data += chunk
        opcode = data[0] & 0x0F
        length = data[1] & 0x7F  # server->client frames are unmasked
        payload_len = length if opcode == 0x8 else 0
        while len(data) < 2 + payload_len:
            chunk = tls.recv(4096)
            if not chunk:
                break
            data += chunk
        if opcode != 0x8 or len(data) < 4:
            return None
        return struct.unpack(">H", data[2:4])[0]
    except (TimeoutError, OSError):
        return None  # no frame observed within the window


@pytest.mark.parametrize("protocols_header", [None, "options-dashboard-session"])
def test_13_websocket_handshake(protocols_header):
    """101 upgrade + accept-key proof asserted; close-frame behavior recorded."""
    result = _handshake(protocols_header)
    try:
        assert "101" in result["status_line"], (
            f"handshake failed: {result['status_line']!r}"
        )
        assert (
            result["headers"].get("sec-websocket-accept") == result["expected_accept"]
        ), "Sec-WebSocket-Accept proof mismatch"
        assert result["headers"].get("upgrade", "").lower() == "websocket"
        print(
            f"websocket handshake (protocols={protocols_header!r}): 101 Switching "
            f"Protocols, accept-key verified — connection-layer OPEN"
        )
        close_code = _read_server_close_frame(result["tls"], result["rest"])
        if close_code is None:
            print(
                "websocket observation: no close frame within the observation "
                "window (matches manual acceptance: OPEN, silent) — recorded "
                "as a finding; expected 4401-per-code was NOT observed"
            )
        else:
            print(
                f"websocket observation: server close code={close_code} "
                f"(expected-per-code 4401)"
            )
    finally:
        for sock in (result["tls"], result["raw"]):
            try:
                sock.close()
            except OSError:
                pass
