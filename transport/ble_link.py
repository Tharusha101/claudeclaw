"""Phase 2b transport: a BLE link to the C3 keytag, with auto-reconnect.

Same wire protocol as the serial link (FRAME / IDLE / BTN lines), carried over
the Nordic UART Service; the pure encode/decode helpers and the generation gate
are reused verbatim.

Hardening:
- If the link dropped, `push_screen` re-scans and reconnects before showing a
  prompt. If it cannot reconnect after a few tries it raises, and the hook
  handler fails closed (deny) — we never approve a prompt the human can't see.
- A disconnect *while* a prompt is up wakes `await_decision` so it raises at
  once (→ deny) instead of hanging until the internal timeout.
- Frames are written in MTU-safe chunks; the keytag reassembles by newline.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import config
from approvals import accepts
from models import Decision
from transport.base import Transport
from transport.serial_link import decode_button, encode_frame, encode_idle


class BleTransport(Transport):
    def __init__(
        self,
        name: str = config.BLE_DEVICE_NAME,
        timeout: float = config.BLE_SCAN_TIMEOUT_S,
        client_factory: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        self._name = name
        self._timeout = timeout
        self._client_factory = client_factory  # test hook: async () -> fake client
        self._client: Any = None
        self._generation = 0
        self._inbox: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        self._buf = ""
        self._disconnected = asyncio.Event()
        self._connect_lock = asyncio.Lock()  # serialize (re)connects
        self._closing = False

    @classmethod
    async def connect(
        cls,
        name: str = config.BLE_DEVICE_NAME,
        timeout: float = config.BLE_SCAN_TIMEOUT_S,
    ) -> BleTransport:
        self = cls(name=name, timeout=timeout)
        await self._establish()
        return self

    # ---- connection management ----

    def _on_disconnect(self, _client: Any) -> None:
        # Called by bleak on the event loop; wake any pending await_decision.
        self._disconnected.set()

    async def _open_client(self) -> Any:
        if self._client_factory is not None:
            client = await self._client_factory()
            client.disconnected_callback = self._on_disconnect  # emulate bleak's ctor
            await client.connect()
            return client
        from bleak import BleakClient, BleakScanner  # imported lazily

        device = await BleakScanner.find_device_by_filter(
            lambda d, adv: adv.local_name == self._name or d.name == self._name,
            timeout=self._timeout,
        )
        if device is None:
            raise RuntimeError(f"BLE keytag {self._name!r} not found — powered and advertising?")
        client = BleakClient(device, disconnected_callback=self._on_disconnect)
        await client.connect()
        return client

    async def _establish(self) -> None:
        client = await self._open_client()
        self._buf = ""
        self._disconnected.clear()
        await client.start_notify(config.BLE_NUS_TX, self._on_notify)
        self._client = client

    async def _ensure_connected(self) -> None:
        if self._client is not None and self._client.is_connected:
            return
        async with self._connect_lock:
            if self._client is not None and self._client.is_connected:
                return
            last: Exception | None = None
            for _ in range(config.BLE_RECONNECT_TRIES):
                try:
                    await self._establish()
                    return
                except Exception as exc:  # noqa: BLE001 - retry with backoff, then fail closed
                    last = exc
                    await asyncio.sleep(config.BLE_RECONNECT_BACKOFF_S)
            raise ConnectionError(f"BLE reconnect to {self._name!r} failed: {last}")

    # ---- I/O ----

    def _on_notify(self, _char: Any, data: bytearray) -> None:
        self._buf += data.decode("ascii", "replace")
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._inbox.put_nowait((line, self._generation))

    async def _write_chunks(self, payload: bytes) -> None:
        for i in range(0, len(payload), config.BLE_CHUNK):
            await self._client.write_gatt_char(
                config.BLE_NUS_RX, payload[i : i + config.BLE_CHUNK], response=True
            )

    async def push_screen(self, lines: list[str]) -> None:
        await self._ensure_connected()  # reconnect if needed; raises -> handler denies
        try:
            await self._write_chunks(encode_frame(lines))
        except Exception:
            self._disconnected.set()
            raise

    async def go_idle(self) -> None:
        # Best-effort only: a disconnected keytag shows its own idle eyes anyway.
        if self._client is None or not self._client.is_connected:
            return
        try:
            await self._write_chunks(encode_idle())
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
                    continue  # stale press from a superseded prompt
                decision = decode_button(line)
                if decision is None:
                    continue  # AUX / noise
                return decision
            raise ConnectionError("keytag disconnected while awaiting a decision")

    async def aclose(self) -> None:
        self._closing = True
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
