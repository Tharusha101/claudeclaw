"""A Transport that answers with a decision the test supplies explicitly.

Never auto-approves: the caller hands it exactly the Decision to return, so a
test that wants to exercise the allow path must say `allow` out loud.
"""

from __future__ import annotations

import asyncio

from models import Decision
from transport.base import Transport


class FakeTransport(Transport):
    def __init__(self, decision: Decision, delay: float = 0.0) -> None:
        self._decision = decision
        self._delay = delay
        self.screens: list[list[str]] = []

    async def push_screen(self, lines: list[str]) -> None:
        self.screens.append(lines)

    async def await_decision(self) -> Decision:
        if self._delay:
            await asyncio.sleep(self._delay)  # used to provoke the internal timeout
        return self._decision
