"""Tests for the serial wire protocol and transport.

The pure encode/decode functions test with no serial port; the round-trip uses
an in-memory fake port so no hardware is involved.
"""

from __future__ import annotations

import asyncio
import queue

import pytest

import config
from models import ALLOW, DENY
from transport.serial_link import (
    SerialTransport,
    decode_button,
    encode_frame,
    encode_idle,
    encode_mood,
)


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


def test_encode_mood():
    assert encode_mood("focus") == b"MOOD FOCUS\n"  # normalizes case
    assert encode_mood("bogus") == b"MOOD AWAKE\n"  # unknown falls back


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


# ---- reconnect after a physical unplug/replug ----
# These drive `_ensure_connected` directly (by pre-setting `_disconnected`)
# rather than racing the real reader thread against a dying fake port -- the
# thread-timing story is already covered by the round-trip test above; what
# needs coverage here is "does a marked-disconnected transport actually use
# the reconnect callable, on both the prompt path and the cosmetic pushes."


def test_push_screen_reconnects_after_a_disconnect():
    async def scenario():
        dead, fresh = _FakePort(), _FakePort()
        transport = SerialTransport(dead, reconnect=lambda: fresh)
        transport._reader_started = True  # pretend a reader already ran and died
        transport._disconnected.set()  # ...and detected the port is gone

        await transport.push_screen(["hello"])

        assert transport._port is fresh
        assert fresh.written and fresh.written[0].startswith(b"FRAME ")
        assert not dead.written  # never touched the dead port

    asyncio.run(scenario())


def test_cosmetic_pushes_also_reconnect():
    # Unlike BLE/WS, serial has no independent trigger that ever reconnects it
    # on its own -- push_screen only runs on a real prompt. Mood/usage/plan
    # pushes must attempt reconnect themselves, or a dropped link never heals.
    async def scenario():
        dead, fresh = _FakePort(), _FakePort()
        transport = SerialTransport(dead, reconnect=lambda: fresh)
        transport._reader_started = True
        transport._disconnected.set()

        await transport.set_mood("FOCUS")

        assert fresh.written == [b"MOOD FOCUS\n"]

    asyncio.run(scenario())


def test_disconnect_without_a_reconnect_callable_fails_closed():
    # A bare port with no `reconnect` (e.g. constructed directly in a test, or
    # any future caller that doesn't know how to reopen it) can't recover --
    # push_screen must raise so the hook handler denies rather than silently
    # approving a prompt no one can see.
    async def scenario():
        transport = SerialTransport(_FakePort())
        transport._reader_started = True
        transport._disconnected.set()

        with pytest.raises(ConnectionError):
            await transport.push_screen(["hello"])

    asyncio.run(scenario())
