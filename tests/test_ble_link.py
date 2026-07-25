"""Tests for the BLE transport, using an in-memory fake client (no radio).

Wire encoding/decoding is covered by test_serial_link; here we check the BLE
behaviours: chunked writes, a notified button becoming a Decision, and the
auto-reconnect hardening (reconnect on the next prompt, fast-deny on drop).
"""

from __future__ import annotations

import asyncio

import pytest

import config
from models import ALLOW
from transport.ble_link import BleTransport


class _FakeClient:
    """Minimal bleak stand-in: records writes, replays notifications, can drop."""

    def __init__(self) -> None:
        self.is_connected = False
        self.written = bytearray()
        self._notify_cb = None
        self.disconnected_callback = None

    async def connect(self) -> None:
        self.is_connected = True

    async def write_gatt_char(self, uuid, data, response=True) -> None:
        if not self.is_connected:
            raise RuntimeError("not connected")
        self.written += bytes(data)

    async def start_notify(self, uuid, callback) -> None:
        self._notify_cb = callback

    async def disconnect(self) -> None:
        self.is_connected = False

    def notify(self, text: str) -> None:
        assert self._notify_cb is not None
        self._notify_cb(None, bytearray(text.encode()))

    def drop(self) -> None:
        self.is_connected = False
        if self.disconnected_callback is not None:
            self.disconnected_callback(self)


def _transport(*clients: _FakeClient) -> BleTransport:
    it = iter(clients)

    async def factory():
        return next(it)

    return BleTransport(client_factory=factory)


def test_push_screen_writes_a_chunked_frame():
    async def scenario():
        fake = _FakeClient()
        t = _transport(fake)
        await t._establish()
        await t.push_screen(["hello"])
        return bytes(fake.written)

    written = asyncio.run(scenario())
    assert written.startswith(b"FRAME ")
    assert written.count(b"\n") == config.ROWS + 1  # header + 8 lines, despite small chunks


def test_notified_button_becomes_a_decision():
    async def scenario():
        fake = _FakeClient()
        t = _transport(fake)
        await t._establish()
        task = asyncio.create_task(t.await_decision())
        await asyncio.sleep(0.02)
        fake.notify("BTN ALLOW\n")
        return await asyncio.wait_for(task, timeout=2)

    assert asyncio.run(scenario()) is ALLOW


def test_disconnect_while_awaiting_raises_fast():
    async def scenario():
        fake = _FakeClient()
        t = _transport(fake)
        await t._establish()
        task = asyncio.create_task(t.await_decision())
        await asyncio.sleep(0.02)
        fake.drop()  # keytag vanishes mid-prompt
        await asyncio.wait_for(task, timeout=2)

    with pytest.raises(ConnectionError):
        asyncio.run(scenario())


def test_push_reconnects_after_a_drop():
    async def scenario():
        first, second = _FakeClient(), _FakeClient()
        t = _transport(first, second)
        await t._establish()  # connects `first`
        first.drop()  # link dies
        await t.push_screen(["hi"])  # must transparently reconnect via `second`
        return bool(second.written), second.written.startswith(b"FRAME ")

    reconnected, wrote_frame = asyncio.run(scenario())
    assert reconnected and wrote_frame
