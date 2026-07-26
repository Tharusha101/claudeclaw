"""The reminder scheduler: pure, deterministic given `now` -- no clock, no
device needed to test it."""

from __future__ import annotations

from datetime import datetime, timedelta

import config
from reminders import CODE, GYM, SUPPLEMENT, WATER, ReminderScheduler


def _at(hhmm: str, day: str = "2026-07-26") -> datetime:
    return datetime.strptime(f"{day} {hhmm}", "%Y-%m-%d %H:%M")


def _drain(s: ReminderScheduler, now: datetime) -> list[str]:
    """Consume every reminder due at `now` -- `due()` returns only one per
    call, priority-ordered, so testing one kind in isolation at a time when an
    earlier-priority kind has also independently crossed its own trigger (and
    hasn't fired yet) needs draining first, the same as a real poll loop would
    naturally do over the course of a day."""
    kinds: list[str] = []
    while True:
        r = s.due(now)
        if r is None:
            return kinds
        kinds.append(r.kind)


def test_gym_fires_once_when_crossed():
    s = ReminderScheduler()
    assert s.due(_at("06:00")) is None  # before GYM_TIME (06:30)
    r = s.due(_at("06:30"))
    assert r is not None and r.kind == GYM
    assert s.due(_at("06:45")) is None  # same day: already fired


def test_gym_fires_again_the_next_day():
    s = ReminderScheduler()
    s.due(_at("06:30", "2026-07-26"))
    r = s.due(_at("06:30", "2026-07-27"))
    assert r is not None and r.kind == GYM


def test_late_poll_still_fires_within_the_grace_window():
    # A poll that lands a bit after the exact minute (delayed loop, missed
    # tick) must still catch it -- this isn't an exact-minute match.
    s = ReminderScheduler()
    r = s.due(_at("06:40"))  # 10 min after GYM_TIME, well within REMINDER_GRACE_MIN
    assert r is not None and r.kind == GYM


def test_reminder_more_than_grace_late_is_skipped_not_shown_stale():
    s = ReminderScheduler()
    late = _at("06:30") + timedelta(minutes=config.REMINDER_GRACE_MIN + 5)
    # Something else may legitimately be due at the same moment (e.g. a
    # supplement time); GYM specifically must never be among them, now or on
    # a later poll -- a stale nudge hours after the fact helps no one.
    assert GYM not in _drain(s, late)
    assert GYM not in _drain(s, late + timedelta(minutes=1))


def test_code_reminder_independent_of_gym():
    s = ReminderScheduler()
    r = s.due(_at(config.CODE_TIME))
    assert r is not None and r.kind == CODE


def test_each_supplement_time_fires_once():
    s = ReminderScheduler()
    first_at, second_at = config.SUPPLEMENT_TIMES
    assert SUPPLEMENT in _drain(s, _at(first_at))
    assert _drain(s, _at(first_at)) == []  # same slot, same day: already fired

    assert SUPPLEMENT in _drain(s, _at(second_at))  # a different slot still fires


def test_water_fires_on_interval_inside_the_active_window():
    s = ReminderScheduler()
    start = _at(config.WATER_ACTIVE_START)
    assert WATER in _drain(s, start)
    assert _drain(s, start + timedelta(minutes=5)) == []  # too soon; nothing else pending either
    assert WATER in _drain(s, start + timedelta(minutes=config.WATER_INTERVAL_MIN))


def test_water_silent_outside_the_active_window():
    s = ReminderScheduler()
    before_window = _at("03:00")
    assert s.due(before_window) is None


def test_one_poll_returns_at_most_one_reminder():
    # If several are simultaneously due, `due` returns a single one per call
    # -- the next poll picks up whatever's still pending.
    s = ReminderScheduler()
    result = s.due(_at(config.GYM_TIME))
    assert result is not None
    assert result.kind == GYM
