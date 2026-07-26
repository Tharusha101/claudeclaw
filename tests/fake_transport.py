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
        self.idle_calls = 0
        self.moods: list[str] = []
        self.usages: list[tuple[float, int, int]] = []
        self.plan_usages: list[tuple[int, int]] = []
        self.reminders: list[str] = []

    async def push_screen(self, lines: list[str]) -> None:
        self.screens.append(lines)

    async def await_decision(self) -> Decision:
        if self._delay:
            await asyncio.sleep(self._delay)  # used to provoke the internal timeout
        return self._decision

    async def go_idle(self) -> None:
        self.idle_calls += 1

    async def set_mood(self, mood: str) -> None:
        self.moods.append(mood)

    async def set_usage(self, cost: float, tokens: int, percent: int) -> None:
        self.usages.append((cost, tokens, percent))

    async def set_plan_usage(self, session_pct: int, week_pct: int) -> None:
        self.plan_usages.append((session_pct, week_pct))

    async def send_reminder(self, kind: str) -> None:
        self.reminders.append(kind)
