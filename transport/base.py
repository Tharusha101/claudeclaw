"""The transport contract. No formatting logic lives here or in any subclass —
`render` has already produced the exact lines; a transport only moves bytes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from models import Decision


class Transport(ABC):
    @abstractmethod
    async def push_screen(self, lines: list[str]) -> None:
        """Display the pre-rendered frame on the keytag."""

    @abstractmethod
    async def await_decision(self) -> Decision:
        """Block until the human answers, returning their explicit allow/deny.

        The internal timeout is enforced by the caller wrapping this in
        `asyncio.wait_for`; an implementation does not need its own deadline.
        """
