"""The real plan-limit parser: `claude`'s plain-text `/usage` render -> PlanUsage."""

from __future__ import annotations

from plan_usage import PlanUsage, parse_usage_output

_SAMPLE = """You are currently using your subscription to power your Claude Code usage

Current session: 61% used · resets Jul 26, 6:09pm (Asia/Colombo)
Current week (all models): 60% used · resets Jul 29, 3:29pm (Asia/Colombo)

What's contributing to your limits usage?
Approximate, based on local sessions on this machine — does not include other devices or claude.ai.
"""

_API_KEY_SAMPLE = """Total cost:            $0.55
Total duration (API):  6m 20s
Total duration (wall): 6h 33m 10s
"""


def test_parses_session_and_week_percent():
    assert parse_usage_output(_SAMPLE) == PlanUsage(session_pct=61, week_pct=60)


def test_returns_none_without_plan_bars():
    # API-key auth shows session cost instead of subscription plan bars.
    assert parse_usage_output(_API_KEY_SAMPLE) is None


def test_returns_none_on_empty_output():
    assert parse_usage_output("") is None
