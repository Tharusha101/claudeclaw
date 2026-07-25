"""Phase 2b transport: a BLE link to the C3 keytag.

Same wire protocol as the serial link (FRAME / IDLE / BTN lines), carried over
the Nordic UART Service: the bridge writes frames to the RX characteristic and
receives button presses as notifications on TX. The pure encode/decode helpers
and the generation gate are reused verbatim — only the bytes' path changes.

Frames are written in MTU-safe chunks; the keytag reassembles them by newline
exactly as it does for serial, so no MTU negotiation is required.
"""

from __future__ import annotations

import asyncio
from typing import Any

import config
from approvals import accepts
from models import Decision
from transport.base import Transport
from transport.serial_link import decode_button, encode_frame, encode_idle


class BleTransport(Transport):
    def __init__(self, client: Any) -> None:
        # `client` is a connected bleak BleakClient (or any object with the same
        # write_gatt_char / start_notify / disconnect surface); injecting it keeps
        # this testable without a radio.
        self._client = client
        self._generation = 0
        self._inbox: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        self._buf = ""
        self._notifying = False

    @classmethod
    async def connect(
        cls,
        name: str = config.BLE_DEVICE_NAME,
        timeout: float = config.BLE_SCAN_TIMEOUT_S,
    ) -> BleTransport:
        from bleak import BleakClient, BleakScanner  # imported lazily

        device = await BleakScanner.find_device_by_filter(
            lambda d, adv: adv.local_name == name or d.name == name,
            timeout=timeout,
        )
        if device is None:
            raise RuntimeError(f"BLE keytag {name!r} not found — is it powered and advertising?")
        client = BleakClient(device)
        await client.connect()
        self = cls(client)
        await self._start_notify()
        return self

    async def _start_notify(self) -> None:
        if self._notifying:
            return
        self._notifying = True

        def on_notify(_char: Any, data: bytearray) -> None:
            # Runs on the event loop. Reassemble lines and stamp each with the
            # on-screen prompt's generation, mirroring the serial reader.
            self._buf += data.decode("ascii", "replace")
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                self._inbox.put_nowait((line, self._generation))

        await self._client.start_notify(config.BLE_NUS_TX, on_notify)

    async def _write(self, payload: bytes) -> None:
        for i in range(0, len(payload), config.BLE_CHUNK):
            await self._client.write_gatt_char(
                config.BLE_NUS_RX, payload[i : i + config.BLE_CHUNK], response=True
            )

    async def push_screen(self, lines: list[str]) -> None:
        await self._write(encode_frame(lines))

    async def go_idle(self) -> None:
        await self._write(encode_idle())

    async def await_decision(self) -> Decision:
        self._generation += 1
        generation = self._generation
        while True:
            line, stamped = await self._inbox.get()
            if not accepts(current=generation, incoming=stamped):
                continue  # stale press from a superseded prompt: discard
            decision = decode_button(line)
            if decision is None:
                continue  # AUX / noise: keep waiting
            return decision

    async def aclose(self) -> None:
        try:
            await self._client.disconnect()
        except Exception:  # noqa: BLE001 - best-effort teardown
            pass
