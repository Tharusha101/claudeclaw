"""OTLP metrics receiver logic: Claude Code cost/token usage into a simple meter.

Claude Code exports `claude_code.cost.usage` (USD) and `claude_code.token.usage`
(tokens) over OTLP. It does NOT expose the actual quota / remaining limit, so
this is a usage *meter* against a budget you set — not the real limit.

Pure parsing here (no framework, no I/O) so it tests without a server. The
receiver endpoint lives in hooks.py; the running totals live in `UsageMeter`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

COST_METRIC = "claude_code.cost.usage"
TOKEN_METRIC = "claude_code.token.usage"


def _attr(dp: Mapping[str, Any], key: str) -> str:
    for a in dp.get("attributes", []):
        if a.get("key") == key:
            return str(a.get("value", {}).get("stringValue", ""))
    return ""


def _value(dp: Mapping[str, Any]) -> float:
    if "asDouble" in dp:
        return float(dp["asDouble"])
    if "asInt" in dp:
        return float(dp["asInt"])
    return 0.0


def parse_metrics(payload: Mapping[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    """Per-session cost (USD) and tokens from one OTLP/JSON export. Values are the
    cumulative counters; token dataPoints (input/output/cache) are summed per session."""
    cost: dict[str, float] = {}
    tokens: dict[str, float] = {}
    for rm in payload.get("resourceMetrics", []):
        for sm in rm.get("scopeMetrics", []):
            for metric in sm.get("metrics", []):
                name = metric.get("name", "")
                if name == COST_METRIC:
                    bucket = cost
                elif name == TOKEN_METRIC:
                    bucket = tokens
                else:
                    continue
                points = (metric.get("sum") or metric.get("gauge") or {}).get("dataPoints", [])
                for dp in points:
                    sid = _attr(dp, "session.id") or "?"
                    bucket[sid] = bucket.get(sid, 0.0) + _value(dp)
    return cost, tokens


class UsageMeter:
    """Running cost/token totals across sessions, against a USD budget."""

    def __init__(self, budget_usd: float) -> None:
        self.budget_usd = budget_usd
        self._cost: dict[str, float] = {}
        self._tokens: dict[str, float] = {}

    def update(self, payload: Mapping[str, Any]) -> None:
        cost, tokens = parse_metrics(payload)
        self._cost.update(cost)  # each export is the session's latest cumulative
        self._tokens.update(tokens)

    @property
    def cost(self) -> float:
        return sum(self._cost.values())

    @property
    def tokens(self) -> int:
        return int(sum(self._tokens.values()))

    @property
    def percent(self) -> int:
        if self.budget_usd <= 0:
            return 0
        return min(999, round(self.cost / self.budget_usd * 100))
