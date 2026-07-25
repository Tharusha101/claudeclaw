"""Wiring and entrypoint.

`create_app` takes the transport as an argument so a test can inject a fake one.
`main` wires the real terminal stub and serves it.
"""

from __future__ import annotations

import argparse
import asyncio

import uvicorn
from fastapi import FastAPI

import config
from hooks import router
from transport.base import Transport
from transport.terminal import TerminalTransport


def create_app(transport: Transport, trace_path: str = config.TRACE_PATH) -> FastAPI:
    app = FastAPI(title="crabtag bridge")
    app.state.transport = transport
    app.state.lock = asyncio.Lock()  # serialize prompts onto the single screen
    app.state.waiting = 0  # in-flight PermissionRequests -> rendered queue depth
    app.state.trace_path = trace_path
    app.include_router(router)
    return app


def _build_transport(serial_port: str | None, baud: int) -> Transport:
    if serial_port:
        from transport.serial_link import SerialTransport  # lazy: needs pyserial

        return SerialTransport.open(serial_port, baud)
    return TerminalTransport()


def main() -> None:
    parser = argparse.ArgumentParser(description="crabtag bridge")
    parser.add_argument(
        "--serial",
        metavar="PORT",
        help="drive the C3 keytag over USB serial on PORT (e.g. COM5); default is terminal stub",
    )
    parser.add_argument("--baud", type=int, default=config.SERIAL_BAUD)
    args = parser.parse_args()

    app = create_app(_build_transport(args.serial, args.baud))
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
