"""Real plan-limit usage: the actual session/week bars from `claude`'s `/usage`
command, not the OTLP-derived $ meter in telemetry.py.

Claude Code exposes no API, hook, or OTLP metric for the real plan quota --
`/usage` is an interactive-only command backed by a private usage endpoint
(confirmed against code.claude.com/docs/en/costs). `claude -p "/usage"` treats
the text as a literal prompt rather than the real command. But piping stdin to
a plain (non-`--print`) invocation whose stdout isn't a TTY makes Claude Code
fall back to a plain-text render of the same dialog -- this shells out to that
and parses it. There is no documented, stable API behind this; if Claude Code
changes the render, `parse_usage_output` starts returning None and the keytag
just keeps showing the last-known bars.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from transport.base import Transport

_SESSION_RE = re.compile(r"Current session:\s*(\d+)%")
_WEEK_RE = re.compile(r"Current week[^:]*:\s*(\d+)%")


@dataclass(frozen=True, slots=True)
class PlanUsage:
    session_pct: int
    week_pct: int


def parse_usage_output(text: str) -> PlanUsage | None:
    """Pure parse of the plain-text `/usage` render. None if the plan-limit
    bars aren't present (e.g. API-key auth, which shows session cost instead
    of a subscription plan)."""
    session = _SESSION_RE.search(text)
    week = _WEEK_RE.search(text)
    if session is None or week is None:
        return None
    return PlanUsage(int(session.group(1)), int(week.group(1)))


async def fetch_plan_usage(timeout_s: float = 20.0) -> PlanUsage | None:
    """Shell out to the real `claude` CLI and ask it for `/usage`. Best-effort:
    any failure (missing binary, timeout, unparseable output) returns None."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude",
            "--no-session-persistence",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return None
    try:
        out, _ = await asyncio.wait_for(proc.communicate(b"/usage\n"), timeout_s)
    except TimeoutError:
        proc.kill()
        return None
    return parse_usage_output(out.decode("utf-8", errors="replace"))


async def sync_once(transport: Transport) -> None:
    """Fetch and push the real plan usage a single time. Shared by the periodic
    poll and an on-demand resync (a long button press on the keytag)."""
    usage = await fetch_plan_usage()
    if usage is not None:
        try:
            await transport.set_plan_usage(usage.session_pct, usage.week_pct)
        except Exception:  # noqa: BLE001 - cosmetic; never take the bridge down
            pass


async def poll_forever(transport: Transport, interval_s: float) -> None:
    """Fetch and push the real plan usage on a loop. Runs until cancelled."""
    while True:
        await sync_once(transport)
        await asyncio.sleep(interval_s)
