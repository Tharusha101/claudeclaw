"""Transport layer: how a screen reaches the keytag and a decision comes back.

Phase 1 ships one implementation (the terminal stub). BLE / WebSocket / phone
relay slot in behind the same `Transport` interface later.
"""

from transport.base import Transport
from transport.terminal import TerminalTransport

__all__ = ["Transport", "TerminalTransport"]
