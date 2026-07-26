"""Daily reminders on the idle screen: gym, coding, water, supplements.

Scheduling runs on real wall-clock time on the bridge, not the device -- the
PC always has a correct clock and timezone, and changing a time is a config
edit, never a reflash. Same reasoning as render.py keeping all screen layout
off the firmware.

`ReminderScheduler.due` is pure and deterministic given `now` and what has
already fired, so it tests without a clock or a device. The periodic push
loop is the only impure part, mirroring plan_usage.py's shape.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
from transport.base import Transport

GYM = "GYM"
CODE = "CODE"
WATER = "WATER"
SUPPLEMENT = "SUPPLEMENT"


@dataclass(frozen=True, slots=True)
class Reminder:
    kind: str


def _minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def _in_window(now: datetime, start: str, end: str) -> bool:
    now_min = now.hour * 60 + now.minute
    return _minutes(start) <= now_min <= _minutes(end)


@dataclass
class ReminderScheduler:
    """One instance per bridge run. `_fired_today` guards each one-off
    reminder to exactly once per calendar day; `_last_water` drives the
    recurring interval instead."""

    _fired_today: dict[str, str] = field(default_factory=dict)
    _last_water: datetime | None = None

    def _fires_once(self, key: str, at: str, now: datetime, today: str) -> bool:
        """True at most once per day, on the first check on or after `at` --
        not an exact-minute match, so a delayed poll never skips a whole day.
        More than REMINDER_GRACE_MIN late (the bridge was off), it still marks
        the day done but does not fire -- a stale nudge hours later helps no one.
        """
        if self._fired_today.get(key) == today:
            return False
        now_min = now.hour * 60 + now.minute
        target_min = _minutes(at)
        if now_min < target_min:
            return False
        self._fired_today[key] = today
        return now_min <= target_min + config.REMINDER_GRACE_MIN

    def due(self, now: datetime) -> Reminder | None:
        today = now.strftime("%Y-%m-%d")

        if self._fires_once(GYM, config.GYM_TIME, now, today):
            return Reminder(GYM)
        if self._fires_once(CODE, config.CODE_TIME, now, today):
            return Reminder(CODE)
        for i, at in enumerate(config.SUPPLEMENT_TIMES):
            if self._fires_once(f"{SUPPLEMENT}_{i}", at, now, today):
                return Reminder(SUPPLEMENT)

        if _in_window(now, config.WATER_ACTIVE_START, config.WATER_ACTIVE_END):
            due_for_water = self._last_water is None or now - self._last_water >= timedelta(
                minutes=config.WATER_INTERVAL_MIN
            )
            if due_for_water:
                self._last_water = now
                return Reminder(WATER)

        return None


async def poll_forever(
    transport: Transport, scheduler: ReminderScheduler, interval_s: float
) -> None:
    """Check the schedule on a loop and push whatever's due. Runs until cancelled."""
    tz = ZoneInfo(config.TIMEZONE)
    while True:
        reminder = scheduler.due(datetime.now(tz))
        if reminder is not None:
            try:
                await transport.send_reminder(reminder.kind)
            except Exception:  # noqa: BLE001 - cosmetic; never take the bridge down
                pass
        await asyncio.sleep(interval_s)
