"""Tests for the serial wire protocol and transport.

The pure encode/decode functions test with no serial port; the round-trip uses
an in-memory fake port so no hardware is involved.
"""

from __future__ import annotations

import asyncio
import queue

import config
from models import ALLOW, DENY
from transport.serial_link import SerialTransport, decode_button, encode_frame, encode_idle


def test_encode_frame_is_fixed_shape():
    text = encode_frame(["Bash", "----"]).decode()
    assert text.startswith(f"FRAME {config.ROWS}\n")
    rows = text.split("\n", 1)[1].split("\n")[: config.ROWS]
    assert len(rows) == config.ROWS
    assert all(len(row) == config.COLS for row in rows)


def test_encode_frame_sanitizes_non_ascii():
    # A narrow ASCII wire: non-printable/Unicode collapses to '?', never raw bytes.
    assert b"caf?" in encode_frame(["café"])


def test_encode_idle_is_the_idle_command():
    assert encode_idle() == b"IDLE\n"


def test_decode_button_maps_allow_and_deny_only():
    assert decode_button("BTN ALLOW\n") is ALLOW
    assert decode_button("BTN DENY") is DENY
    assert decode_button("BTN AUX") is None  # reserved, not a decision
    assert decode_button("READY") is None
    assert decode_button("garbage") is None


class _FakePort:
    """Minimal duck-typed pyserial stand-in: blocking readline() + write()."""

    def __init__(self) -> None:
        self.written: list[bytes] = []
        self._in: queue.Queue[bytes] = queue.Queue()

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def readline(self) -> bytes:
        return self._in.get()

    def feed(self, line: str) -> None:
        self._in.put(line.encode())


def test_serial_transport_pushes_a_frame_and_reads_a_button():
    async def scenario():
        port = _FakePort()
        transport = SerialTransport(port)

        await transport.push_screen(["hello"])
        assert port.written and port.written[0].startswith(b"FRAME ")

        task = asyncio.create_task(transport.await_decision())
        await asyncio.sleep(0.05)  # let the reader start under this generation
        port.feed("BTN ALLOW\n")
        return await asyncio.wait_for(task, timeout=2)

    assert asyncio.run(scenario()) is ALLOW
