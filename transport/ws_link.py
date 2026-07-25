"""Phase 2c transport: a WiFi/WebSocket link to the C3 keytag ("away" mode).

Unlike serial and BLE, here the keytag is the *client*: it connects out to a
WebSocket endpoint on the bridge (so it works behind a phone hotspot / NAT, and
over a tunnel from anywhere). The bridge holds whichever keytag is currently
connected; the endpoint (in hooks.py) authenticates the token, accepts the
socket, and hands it to `register`.

Same line protocol (FRAME / IDLE / BTN), same generation gate. Fails closed: if
no keytag is connected when a prompt arrives, `push_screen` waits briefly and
then raises so the hook handler denies — we never approve a prompt no one saw.
"""

from __future__ import annotations

import asyncio
from typing import Any

import config
from approvals import accepts
from models import Decision
from transport.base import Transport
from transport.serial_link import decode_button, encode_frame, encode_idle


class WsTransport(Transport):
    def __init__(self, token: str) -> None:
        self._token = token
        self._ws: Any = None  # the currently connected keytag socket
        self._generation = 0
        self._inbox: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        self._buf = ""
        self._connected = asyncio.Event()
        self._disconnected = asyncio.Event()

    @property
    def token(self) -> str:
        return self._token

    async def register(self, websocket: Any) -> None:
        """Own a freshly accepted keytag socket for its lifetime. Called by the
        WebSocket endpoint after it has authenticated the token."""
        self._ws = websocket
        self._buf = ""
        self._disconnected.clear()
        self._connected.set()
        try:
            async for message in websocket.iter_text():
                self._feed(message)
        finally:
            # Only tear down shared state if THIS socket is still the active one.
            # A stale socket (replaced by a fresh reconnect) must not clobber the
            # live connection's state or spuriously signal a disconnect.
            if self._ws is websocket:
                self._ws = None
                self._connected.clear()
                self._disconnected.set()

    def _feed(self, text: str) -> None:
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._inbox.put_nowait((line, self._generation))

    async def _require_connection(self) -> None:
        if self._ws is not None:
            return
        try:
            await asyncio.wait_for(self._connected.wait(), config.WS_CONNECT_WAIT_S)
        except TimeoutError as exc:
            raise ConnectionError("no keytag connected") from exc

    async def push_screen(self, lines: list[str]) -> None:
        await self._require_connection()  # raises -> handler denies if nobody is there
        await self._ws.send_text(encode_frame(lines).decode("ascii"))

    async def go_idle(self) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send_text(encode_idle().decode("ascii"))
        except Exception:  # noqa: BLE001 - cosmetic
            self._disconnected.set()

    async def await_decision(self) -> Decision:
        self._generation += 1
        generation = self._generation
        while True:
            getter = asyncio.ensure_future(self._inbox.get())
            dropped = asyncio.ensure_future(self._disconnected.wait())
            done, pending = await asyncio.wait(
                {getter, dropped}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            if getter in done:  # a press wins over a disconnect
                line, stamped = getter.result()
                if not accepts(current=generation, incoming=stamped):
                    continue
                decision = decode_button(line)
                if decision is None:
                    continue
                return decision
            raise ConnectionError("keytag disconnected while awaiting a decision")
