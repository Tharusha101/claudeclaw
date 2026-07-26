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
from collections.abc import Callable
from typing import Any

import config
from approvals import accepts
from models import ALLOW, DENY, Decision
from transport.base import Transport

FRAME_HEADER = "FRAME"
BTN_PREFIX = "BTN"
IDLE_COMMAND = "IDLE"
MOOD_COMMAND = "MOOD"
MOODS = ("AWAKE", "SLEEPY", "FOCUS", "DIZZY", "SMOKE", "COOK")
PLAN_COMMAND = "PLAN"


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


def encode_mood(mood: str) -> bytes:
    """The command that sets the idle-face mood. Unknown moods fall back to AWAKE."""
    name = mood.upper()
    if name not in MOODS:
        name = "AWAKE"
    return f"{MOOD_COMMAND} {name}\n".encode("ascii")


def encode_usage(cost: float, tokens: int, percent: int) -> bytes:
    """The command that updates the keytag's usage meter: cost USD, tokens, budget %."""
    return f"USAGE {cost:.2f} {int(tokens)} {int(percent)}\n".encode("ascii")


def encode_plan_usage(session_pct: int, week_pct: int) -> bytes:
    """The command that updates the keytag's real plan-limit display: the actual
    `/usage` command's session and week percentages."""
    return f"{PLAN_COMMAND} {int(session_pct)} {int(week_pct)}\n".encode("ascii")


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
    def __init__(self, port: Any, reconnect: Callable[[], Any] | None = None) -> None:
        # `port` is a pyserial Serial (or any object with blocking readline() and
        # write(bytes)); injecting it keeps this testable without real hardware.
        # `reconnect` is a zero-arg callable that opens a fresh port with the same
        # name/baud -- a physical unplug kills the OS-level handle even though the
        # port usually re-enumerates under the same name. Without it (e.g. a bare
        # fake port in a test), a disconnect just fails closed with no recovery.
        self._port = port
        self._reconnect = reconnect
        self._generation = 0
        self._inbox: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        self._reader_started = False
        self._disconnected = asyncio.Event()
        self._connect_lock = asyncio.Lock()  # serialize reconnect attempts

    @classmethod
    def open(cls, port_name: str, baud: int = config.SERIAL_BAUD) -> SerialTransport:
        import serial  # pyserial, imported lazily so terminal-only runs don't need it

        def reconnect() -> Any:
            return serial.Serial(port_name, baud, timeout=None)

        return cls(reconnect(), reconnect=reconnect)

    def _start_reader(self) -> None:
        loop = asyncio.get_running_loop()
        inbox = self._inbox
        port = self._port

        def pump() -> None:
            while True:
                try:
                    raw = port.readline()
                except Exception:  # noqa: BLE001 - device gone; signal, thread exits
                    loop.call_soon_threadsafe(self._disconnected.set)
                    return
                if not raw:
                    continue
                line = raw.decode("ascii", "replace")
                # Stamp with the on-screen prompt's generation at read time.
                loop.call_soon_threadsafe(inbox.put_nowait, (line, self._generation))

        threading.Thread(target=pump, name="keytag-serial", daemon=True).start()

    def _ensure_reader(self) -> None:
        if self._reader_started:
            return
        self._reader_started = True
        self._start_reader()

    async def _ensure_connected(self) -> None:
        if not self._disconnected.is_set():
            return
        if self._reconnect is None:
            raise ConnectionError("keytag serial port disconnected (no reconnect configured)")
        async with self._connect_lock:
            if not self._disconnected.is_set():
                return  # a concurrent caller already reconnected
            last: Exception | None = None
            for _ in range(config.SERIAL_RECONNECT_TRIES):
                try:
                    self._port = await asyncio.to_thread(self._reconnect)
                    self._disconnected.clear()
                    self._start_reader()  # the old reader thread already exited
                    return
                except Exception as exc:  # noqa: BLE001 - retry with backoff, then fail closed
                    last = exc
                    await asyncio.sleep(config.SERIAL_RECONNECT_BACKOFF_S)
            raise ConnectionError(f"serial reconnect failed: {last}")

    async def push_screen(self, lines: list[str]) -> None:
        await self._ensure_connected()  # reconnect if needed; raises -> handler denies
        await asyncio.to_thread(self._port.write, encode_frame(lines))

    async def go_idle(self) -> None:
        await self._best_effort(encode_idle())

    async def set_mood(self, mood: str) -> None:
        await self._best_effort(encode_mood(mood))

    async def set_usage(self, cost: float, tokens: int, percent: int) -> None:
        await self._best_effort(encode_usage(cost, tokens, percent))

    async def set_plan_usage(self, session_pct: int, week_pct: int) -> None:
        await self._best_effort(encode_plan_usage(session_pct, week_pct))

    async def _best_effort(self, payload: bytes) -> None:
        # Unlike BLE/WS, serial has no other trigger that ever reconnects it (no
        # advertising, no client dialing back in) -- push_screen only runs on a
        # real prompt, which may be a long time away. So these cosmetic pushes
        # actively attempt reconnect too; it's how a dropped mood/usage/plan-usage
        # link self-heals on the next periodic push instead of staying dark
        # forever after a replug.
        try:
            await self._ensure_connected()
            await asyncio.to_thread(self._port.write, payload)
        except Exception:  # noqa: BLE001 - cosmetic
            pass

    async def await_decision(self) -> Decision:
        self._ensure_reader()
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
                    continue  # stale press from a superseded prompt: discard
                decision = decode_button(line)
                if decision is None:
                    continue  # AUX / READY / noise: keep waiting
                return decision
            raise ConnectionError("keytag disconnected while awaiting a decision")
