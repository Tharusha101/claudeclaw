"""Phase 2a transport: a USB serial link to the C3 keytag.

The wire protocol is deliberately line-oriented ASCII so it reads straight in a
serial monitor during bring-up:

    bridge -> C3 :  "FRAME 8\n" then 8 lines, each exactly COLS chars, ASCII,
                    space-padded. The C3 draws them verbatim.
    C3 -> bridge :  "BTN ALLOW\n" / "BTN DENY\n" / "BTN AUX\n" (and "READY" on
                    boot). The bridge maps ALLOW/DENY to a Decision; AUX is
                    reserved.

`encode_frame` / `decode_button` are pure and test without a serial port. The
transport reuses the same generation gate as the terminal stub: a button press
stamped under a superseded prompt is discarded, never applied to the next one.

No formatting lives here — `render` already produced the lines. This module only
makes them safe for a narrow ASCII wire (sanitize + pad) and frames them.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import config
from approvals import accepts
from models import ALLOW, DENY, Decision
from transport.base import Transport

FRAME_HEADER = "FRAME"
BTN_PREFIX = "BTN"
IDLE_COMMAND = "IDLE"


def _sanitize(line: str) -> str:
    """Coerce a rendered line to exactly COLS printable-ASCII chars."""
    safe = "".join(ch if " " <= ch <= "~" else "?" for ch in line)
    return safe[: config.COLS].ljust(config.COLS)


def encode_frame(lines: list[str]) -> bytes:
    """Serialize a rendered frame for the wire: a header plus ROWS fixed lines."""
    rows = [_sanitize(line) for line in lines][: config.ROWS]
    while len(rows) < config.ROWS:
        rows.append(" " * config.COLS)
    body = "".join(row + "\n" for row in rows)
    return f"{FRAME_HEADER} {config.ROWS}\n{body}".encode("ascii")


def encode_idle() -> bytes:
    """The command that returns the keytag to its idle (crab-face) screen."""
    return f"{IDLE_COMMAND}\n".encode("ascii")


def decode_button(line: str) -> Decision | None:
    """Map a device line to a Decision. Anything else (AUX, READY, noise) is None."""
    parts = line.strip().split()
    if len(parts) == 2 and parts[0] == BTN_PREFIX:
        if parts[1] == "ALLOW":
            return ALLOW
        if parts[1] == "DENY":
            return DENY
    return None


class SerialTransport(Transport):
    def __init__(self, port: Any) -> None:
        # `port` is a pyserial Serial (or any object with blocking readline() and
        # write(bytes)); injecting it keeps this testable without real hardware.
        self._port = port
        self._generation = 0
        self._inbox: asyncio.Queue[tuple[str, int]] | None = None
        self._reader_started = False

    @classmethod
    def open(cls, port_name: str, baud: int = config.SERIAL_BAUD) -> SerialTransport:
        import serial  # pyserial, imported lazily so terminal-only runs don't need it

        return cls(serial.Serial(port_name, baud, timeout=None))

    def _ensure_reader(self) -> None:
        if self._reader_started:
            return
        self._reader_started = True
        loop = asyncio.get_running_loop()
        self._inbox = asyncio.Queue()
        inbox = self._inbox

        def pump() -> None:
            while True:
                raw = self._port.readline()
                if not raw:
                    continue
                line = raw.decode("ascii", "replace")
                # Stamp with the on-screen prompt's generation at read time.
                loop.call_soon_threadsafe(inbox.put_nowait, (line, self._generation))

        threading.Thread(target=pump, name="keytag-serial", daemon=True).start()

    async def push_screen(self, lines: list[str]) -> None:
        await asyncio.to_thread(self._port.write, encode_frame(lines))

    async def go_idle(self) -> None:
        await asyncio.to_thread(self._port.write, encode_idle())

    async def await_decision(self) -> Decision:
        self._ensure_reader()
        assert self._inbox is not None
        self._generation += 1
        generation = self._generation
        while True:
            line, stamped = await self._inbox.get()
            if not accepts(current=generation, incoming=stamped):
                continue  # stale press from a superseded prompt: discard
            decision = decode_button(line)
            if decision is None:
                continue  # AUX / READY / noise: keep waiting
            return decision
