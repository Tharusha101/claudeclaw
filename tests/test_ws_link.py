"""Tests for the WiFi/WebSocket transport and its token auth.

The transport logic uses a fake socket; the auth is exercised end-to-end through
the real ASGI app with the TestClient's WebSocket support.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import config
from bridge import create_app
from models import ALLOW
from transport.ws_link import WsTransport


class _FakeWS:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


def test_push_and_button_round_trip():
    async def scenario():
        t = WsTransport("tok")
        ws = _FakeWS()
        t._ws = ws  # simulate a connected keytag
        t._connected.set()

        await t.push_screen(["hello"])
        assert ws.sent and ws.sent[0].startswith("FRAME ")

        task = asyncio.create_task(t.await_decision())
        await asyncio.sleep(0.02)
        t._feed("BTN ALLOW\n")  # a message arrived from the keytag
        return await asyncio.wait_for(task, timeout=2)

    assert asyncio.run(scenario()) is ALLOW


def test_push_with_no_keytag_fails_closed(monkeypatch):
    # No keytag connected: push_screen must raise (the handler then denies).
    monkeypatch.setattr(config, "WS_CONNECT_WAIT_S", 0.05)

    async def scenario():
        await WsTransport("tok").push_screen(["x"])

    with pytest.raises(ConnectionError):
        asyncio.run(scenario())


def _app():
    return create_app(WsTransport("secret"), keytag_token="secret")


def test_ws_endpoint_rejects_wrong_token():
    client = TestClient(_app())
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"{config.WS_PATH}?token=wrong"):
            pass


def test_ws_endpoint_rejects_missing_token():
    client = TestClient(_app())
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(config.WS_PATH):
            pass


def test_ws_endpoint_accepts_correct_token():
    client = TestClient(_app())
    with client.websocket_connect(f"{config.WS_PATH}?token=secret") as ws:
        ws.send_text("BTN AUX\n")  # connected; keytag can talk (AUX is ignored)
    # exiting the context without a WebSocketDisconnect on entry == accepted
