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
import secrets
from typing import Any

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import JSONResponse

import config
from approvals import Outcome, resolve
from models import DENY, Decision, PermissionRequestEvent
from render import render
from transport.base import Transport

router = APIRouter()


@router.websocket(config.WS_PATH)
async def keytag_socket(websocket: WebSocket) -> None:
    """Inbound WebSocket from a WiFi keytag (phase 2c). Authenticate the shared
    token before accepting, then hand the socket to the WsTransport. A missing or
    wrong token is rejected outright — this channel carries approval decisions,
    so an unauthenticated peer must never be able to send one."""
    expected = getattr(websocket.app.state, "keytag_token", "")
    provided = websocket.query_params.get("token", "")
    if not expected or not secrets.compare_digest(provided, expected):
        await websocket.close(code=1008)  # policy violation, before accept -> rejected
        return
    register = getattr(websocket.app.state.transport, "register", None)
    if register is None:  # bridge isn't in WebSocket mode
        await websocket.close(code=1011)
        return
    await websocket.accept()
    await register(websocket)


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


# ── Mood hooks: informational events that set the idle-face mood ────────────
# None of these block or return a decision — a bare 200 lets Claude Code carry
# on, and a failed mood update must never disturb a session.


def _ok() -> JSONResponse:
    return JSONResponse(status_code=200, content={})


async def _set_mood(transport: Transport, mood: str) -> None:
    try:
        await transport.set_mood(mood)
    except Exception:  # noqa: BLE001 - cosmetic
        pass


@router.post("/hooks/user-prompt-submit")
async def user_prompt_submit(request: Request) -> JSONResponse:
    await _set_mood(request.app.state.transport, "FOCUS")  # a turn is running
    return _ok()


@router.post("/hooks/stop")
async def stop(request: Request) -> JSONResponse:
    await _set_mood(request.app.state.transport, "SLEEPY")  # turn finished -> idle
    return _ok()


@router.post("/hooks/notification")
async def notification(request: Request) -> JSONResponse:
    await _set_mood(request.app.state.transport, "SLEEPY")  # idle / waiting
    return _ok()


@router.post("/hooks/stop-failure")
async def stop_failure(request: Request) -> JSONResponse:
    await _set_mood(request.app.state.transport, "DIZZY")  # rate-limited / overloaded
    return _ok()


# ── Usage meter: OTLP metrics in, totals out ───────────────────────────────


async def _push_usage(transport: Transport, meter: Any) -> None:
    try:
        await transport.set_usage(meter.cost, meter.tokens, meter.percent)
    except Exception:  # noqa: BLE001 - cosmetic
        pass


@router.post(config.OTLP_METRICS_PATH)
async def otlp_metrics(request: Request) -> JSONResponse:
    """Claude Code's OTLP/JSON metric export -> update the meter -> push to keytag.
    Always 200 so the exporter keeps sending; telemetry must never break a session."""
    state = request.app.state
    try:
        state.usage.update(json.loads(await request.body()))
        await _push_usage(state.transport, state.usage)
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse(status_code=200, content={})


@router.get("/usage")
async def usage(request: Request) -> JSONResponse:
    meter = request.app.state.usage
    return JSONResponse(
        {
            "cost_usd": round(meter.cost, 4),
            "tokens": meter.tokens,
            "budget_usd": meter.budget_usd,
            "percent": meter.percent,
        }
    )


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
                try:
                    await transport.go_idle()  # back to the idle screen
                except Exception:  # noqa: BLE001 - cosmetic; never affects the decision
                    pass
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
