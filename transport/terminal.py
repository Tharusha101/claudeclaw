"""Phase 1 transport: a terminal stub.

It prints what the 240x240 screen would show and reads a single y/n keypress.
No msvcrt/termios split and no raw-mode trickery — plain `input()`. That code's
only future is deletion in phase 2 when the buttons become real, so it isn't
worth writing.

The generation gate is the load-bearing part. A persistent reader thread stamps
every line with the generation of the prompt that was on screen when it was
read. `await_decision` accepts a line only if its stamp matches the prompt it is
serving; a keystroke left over from a prompt that already timed out is discarded
instead of silently answering the next one.
"""

from __future__ import annotations

import asyncio
import sys
import threading

import config
from approvals import accepts
from models import ALLOW, DENY, Decision
from transport.base import Transport


def parse_key(line: str) -> Decision | None:
    """y -> allow, n -> deny, anything else -> None (ignore, keep waiting)."""
    key = line.strip().lower()
    if key == config.KEY_ALLOW:
        return ALLOW
    if key == config.KEY_DENY:
        return DENY
    return None


class TerminalTransport(Transport):
    def __init__(self) -> None:
        self._generation = 0
        self._inbox: asyncio.Queue[tuple[str, int]] | None = None
        self._reader_started = False

    def _ensure_reader(self) -> None:
        if self._reader_started:
            return
        self._reader_started = True
        loop = asyncio.get_running_loop()
        self._inbox = asyncio.Queue()
        inbox = self._inbox

        def pump() -> None:
            for line in sys.stdin:
                # Stamp with the on-screen prompt's generation at read time.
                # A single int read under the GIL; no lock needed.
                stamped = (line.rstrip("\n"), self._generation)
                loop.call_soon_threadsafe(inbox.put_nowait, stamped)

        threading.Thread(target=pump, name="keytag-stdin", daemon=True).start()

    async def push_screen(self, lines: list[str]) -> None:
        # Frame it so the stub reads like the physical screen would look.
        border = "+" + "-" * config.COLS + "+"
        sys.stdout.write("\n" + border + "\n")
        for line in lines:
            sys.stdout.write("|" + line.ljust(config.COLS) + "|\n")
        sys.stdout.write(border + "\n")
        sys.stdout.write(f"[{config.KEY_ALLOW}] allow   [{config.KEY_DENY}] deny > ")
        sys.stdout.flush()

    async def await_decision(self) -> Decision:
        self._ensure_reader()
        assert self._inbox is not None
        self._generation += 1
        generation = self._generation
        while True:
            line, stamped = await self._inbox.get()
            if not accepts(current=generation, incoming=stamped):
                continue  # stale keystroke from a superseded prompt: discard
            decision = parse_key(line)
            if decision is None:
                continue  # not a y/n: ignore and keep waiting
            return decision
