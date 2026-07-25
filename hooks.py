"""HTTP endpoint for the PermissionRequest hook.

The whole safety story lives in `_handle`. Two rules, both non-negotiable:

1. Every path returns HTTP 200 with an explicit decision. For HTTP hooks a
   non-2xx is a *non-blocking error* — Claude Code continues, i.e. the tool is
   allowed. So even a deny must be a 200, and the body must never be rejected by
   framework validation before our code runs. That is why the body is read raw
   and parsed by hand instead of via a Pydantic model that could 422 on us.

2. The handler cannot fall off the end. The happy return, the timeout branch,
   and the catch-all `except` all return a decision. `asyncio.CancelledError`
   is BaseException, not Exception, so it is intentionally *not* caught — a
   cancelled request means Claude Code already gave up, and our internal
   timeout fires long before that.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import config
from approvals import Outcome, resolve
from models import DENY, Decision, PermissionRequestEvent
from render import render
from transport.base import Transport

router = APIRouter()


def _respond(decision: Decision) -> JSONResponse:
    """The documented PermissionRequest output shape, always at HTTP 200."""
    return JSONResponse(
        status_code=200,
        content={
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {"behavior": decision.behavior},
            }
        },
    )


def _trace(path: str, record: dict[str, Any]) -> None:
    """Append one JSONL line. Best-effort: tracing must never break a decision."""
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:  # noqa: BLE001 - a failed trace write must not deny a real request
        pass


@router.post(config.HOOK_PATH)
async def permission_request(request: Request) -> JSONResponse:
    state = request.app.state
    return await _handle(request, state.transport, state, state.trace_path)


async def _handle(
    request: Request,
    transport: Transport,
    state: Any,
    trace_path: str,
) -> JSONResponse:
    try:
        raw = await request.body()
        event = PermissionRequestEvent.from_mapping(json.loads(raw))
        _trace(
            trace_path,
            {
                "event": "PermissionRequest",
                "tool": event.tool_name,
                "input": dict(event.tool_input),
            },
        )

        # Serialize: one prompt on the single screen at a time. `waiting` is the
        # queue depth we render, so three parallel Bash calls read as a finite
        # "3" rather than an infinite loop.
        state.waiting += 1
        try:
            async with state.lock:
                depth = state.waiting
                await transport.push_screen(render(event, depth))
                try:
                    answer = await asyncio.wait_for(
                        transport.await_decision(), config.DECISION_TIMEOUT_S
                    )
                    decision = resolve(Outcome.ANSWERED, answer)
                except TimeoutError:
                    decision = resolve(Outcome.TIMEOUT, None)  # explicit deny
        finally:
            state.waiting -= 1

        _trace(
            trace_path,
            {"event": "decision", "tool": event.tool_name, "behavior": decision.behavior},
        )
        return _respond(decision)

    except Exception as exc:  # noqa: BLE001 - fail closed: log, then deny. Never swallow silently.
        _trace(trace_path, {"event": "error", "error": repr(exc)})
        return _respond(DENY)
