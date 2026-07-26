"""Wiring and entrypoint.

`create_app` takes either a ready transport (terminal / serial / a test fake) or
an async `connect` factory (BLE, which must connect inside the server's event
loop). `main` picks one from the command line and serves it.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

import config
import plan_usage
from hooks import router
from telemetry import UsageMeter
from transport.base import Transport
from transport.terminal import TerminalTransport

Connect = Callable[[], Awaitable[Transport]]


def create_app(
    transport: Transport | None = None,
    trace_path: str = config.TRACE_PATH,
    connect: Connect | None = None,
    keytag_token: str = "",
    budget_usd: float = config.USAGE_BUDGET_USD,
    poll_plan_usage: bool = False,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if connect is not None:  # BLE: connect inside the running loop
            app.state.transport = await connect()
        task = None
        if poll_plan_usage:  # real /usage bars: only for actual device runs, never tests
            task = asyncio.create_task(
                plan_usage.poll_forever(app.state.transport, config.PLAN_USAGE_POLL_S)
            )
        yield
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        aclose = getattr(getattr(app.state, "transport", None), "aclose", None)
        if aclose is not None:
            await aclose()

    app = FastAPI(title="crabtag bridge", lifespan=lifespan)
    app.state.transport = transport
    app.state.keytag_token = keytag_token  # for the WiFi keytag WebSocket auth
    app.state.lock = asyncio.Lock()  # serialize prompts onto the single screen
    app.state.waiting = 0  # in-flight PermissionRequests -> rendered queue depth
    app.state.usage = UsageMeter(budget_usd)  # cost/token totals from OTLP
    app.state.trace_path = trace_path
    app.include_router(router)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="crabtag bridge")
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument(
        "--serial",
        metavar="PORT",
        help="drive the C3 keytag over USB serial on PORT (e.g. COM5)",
    )
    transport.add_argument(
        "--ble",
        action="store_true",
        help="drive the C3 keytag over BLE (scans for the 'crabtag' device)",
    )
    transport.add_argument(
        "--ws",
        action="store_true",
        help="wait for a WiFi keytag to connect over WebSocket (needs KEYTAG_TOKEN in env)",
    )
    parser.add_argument("--baud", type=int, default=config.SERIAL_BAUD)
    parser.add_argument(
        "--lan",
        action="store_true",
        help="with --ws, also listen on the LAN (0.0.0.0) for a direct WiFi keytag; "
        "omit when behind a tunnel — cloudflared connects on localhost",
    )
    args = parser.parse_args()

    budget = float(os.environ.get("KEYTAG_BUDGET_USD", config.USAGE_BUDGET_USD))

    if args.ws:
        token = os.environ.get("KEYTAG_TOKEN", "")
        if not token:
            parser.error("--ws requires a shared secret in KEYTAG_TOKEN (must match the firmware)")
        from transport.ws_link import WsTransport

        app = create_app(
            WsTransport(token), keytag_token=token, budget_usd=budget, poll_plan_usage=True
        )
    elif args.ble:
        from transport.ble_link import BleTransport  # lazy: needs bleak

        app = create_app(connect=BleTransport.connect, budget_usd=budget, poll_plan_usage=True)
    elif args.serial:
        from transport.serial_link import SerialTransport  # lazy: needs pyserial

        app = create_app(
            SerialTransport.open(args.serial, args.baud), budget_usd=budget, poll_plan_usage=True
        )
    else:
        app = create_app(TerminalTransport(), budget_usd=budget)

    # Behind a tunnel (the intended --ws deployment) cloudflared connects on
    # localhost, so bind localhost by default and keep the bridge off the LAN.
    # --lan opts into 0.0.0.0 for a direct-WiFi keytag test only.
    host = "0.0.0.0" if (args.ws and args.lan) else config.HOST  # noqa: S104
    uvicorn.run(app, host=host, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
