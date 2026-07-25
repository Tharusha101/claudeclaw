"""Tests for the BLE transport, using an in-memory fake client (no radio).

The wire encoding/decoding is already covered by test_serial_link; here we check
that BleTransport writes a frame in chunks and turns a notified button into a
Decision through the generation gate.
"""

from __future__ import annotations

import asyncio

import config
from models import ALLOW
from transport.ble_link import BleTransport


class _FakeClient:
    """Minimal bleak stand-in: records writes, replays notifications."""

    def __init__(self) -> None:
        self.written = bytearray()
        self._cb = None

    async def write_gatt_char(self, uuid, data, response=True) -> None:
        self.written += bytes(data)

    async def start_notify(self, uuid, callback) -> None:
        self._cb = callback

    async def disconnect(self) -> None:
        pass

    def notify(self, text: str) -> None:
        assert self._cb is not None
        self._cb(None, bytearray(text.encode()))


def test_push_screen_writes_a_chunked_frame():
    async def scenario():
        client = _FakeClient()
        transport = BleTransport(client)
        await transport.push_screen(["hello"])
        return bytes(client.written)

    written = asyncio.run(scenario())
    assert written.startswith(b"FRAME ")
    # 8 lines of COLS chars + header, all delivered despite the small chunk size
    assert written.count(b"\n") == config.ROWS + 1


def test_notified_button_becomes_a_decision():
    async def scenario():
        client = _FakeClient()
        transport = BleTransport(client)
        await transport._start_notify()
        task = asyncio.create_task(transport.await_decision())
        await asyncio.sleep(0.02)
        client.notify("BTN ALLOW\n")  # a press arrives, possibly split by BLE
        return await asyncio.wait_for(task, timeout=2)

    assert asyncio.run(scenario()) is ALLOW
