"""The transport contract. No formatting logic lives here or in any subclass —
`render` has already produced the exact lines; a transport only moves bytes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from models import Decision


class Transport(ABC):
    async def start(self) -> None:
        """Begin listening for inbound lines (buttons, RESYNC, ...) as soon as
        the transport is up, not just once the first prompt calls
        `await_decision`. Default no-op: BLE/WS already listen eagerly as part
        of their connection setup; only serial needs this."""
        return None

    def on_resync(self, callback: Callable[[], Awaitable[None]]) -> None:
        """Register a callback fired when the keytag asks for a fresh resync of
        its mood/usage state (a long button press) -- an out-of-band request,
        not an allow/deny decision. Default no-op; only transports with a
        listening line-reader implement this."""
        return None

    @abstractmethod
    async def push_screen(self, lines: list[str]) -> None:
        """Display the pre-rendered frame on the keytag."""

    @abstractmethod
    async def await_decision(self) -> Decision:
        """Block until the human answers, returning their explicit allow/deny.

        The internal timeout is enforced by the caller wrapping this in
        `asyncio.wait_for`; an implementation does not need its own deadline.
        """

    async def go_idle(self) -> None:
        """Return the display to its idle state after a prompt resolves.

        Default no-op: transports without an idle screen (the terminal stub)
        simply ignore it. Cosmetic — callers must not let it affect a decision.
        """
        return None

    async def set_mood(self, mood: str) -> None:
        """Set the idle-face mood to mirror Claude Code's state (sleepy, focus,
        dizzy, ...). Default no-op; only display transports use it."""
        return None

    async def set_usage(self, cost: float, tokens: int, percent: int) -> None:
        """Update the keytag's usage meter. Default no-op; only display transports use it."""
        return None

    async def set_plan_usage(self, session_pct: int, week_pct: int) -> None:
        """Update the keytag's real plan-limit display (session/week %, from
        the actual `/usage` command). Default no-op; only display transports use it."""
        return None

    async def send_reminder(self, kind: str) -> None:
        """Show a reminder banner (gym/code/water/supplement) on the idle
        screen. Default no-op; only display transports use it."""
        return None
