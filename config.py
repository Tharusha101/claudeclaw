"""Tunables only. No logic, no imports from other project modules.

Every magic number the rest of the codebase might reach for lives here. The
screen glyphs live here too: the real TFT font may be ASCII-only, and hunting
special characters across modules later is exactly the kind of pain this
centralization avoids.
"""

# ── Network ────────────────────────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 8787
HOOK_PATH = "/hooks/permission-request"

# ── Usage meter ────────────────────────────────────────────────────────────
# Claude Code reports cost/tokens but not the real quota, so the keytag shows
# usage against this budget. Override with KEYTAG_BUDGET_USD.
USAGE_BUDGET_USD = 20.0
OTLP_METRICS_PATH = "/v1/metrics"  # point Claude Code's OTLP metrics exporter here

# ── Decision timing ────────────────────────────────────────────────────────
# Internal deadline for a human answer. Must stay comfortably under the hook's
# own `timeout` (default 600s) so the bridge answers rather than the hook giving
# up. A timeout-deny is cheap (Claude tells me, I re-run); a silently frozen
# agent I don't know about is expensive, and on real hardware a long hold is a
# lit screen and a live radio burning the daily power budget.
DECISION_TIMEOUT_S = 120

# ── Screen geometry ────────────────────────────────────────────────────────
COLS = 20
ROWS = 8
PAYLOAD_ROWS = 3          # rows 3–5 carry the payload
PAYLOAD_BUDGET = 60       # truncate to fit 60, then wrap to COLS across PAYLOAD_ROWS

# ── Screen glyphs (ASCII-safe for the real font) ───────────────────────────
ELLIPSIS = "..."
QUEUE_GLYPH = "|"
DENY_GLYPH = "x"
ALLOW_GLYPH = "v"
DENY_LABEL = "deny"
ALLOW_LABEL = "allow"
UNKNOWN_PAYLOAD = "? unknown payload"

DIVIDER = "-" * COLS

# Deny on the left, allow on the right; the glyphs map to physical buttons later.
_DENY_AFFORDANCE = f"{DENY_GLYPH} {DENY_LABEL}"
_ALLOW_AFFORDANCE = f"{ALLOW_LABEL} {ALLOW_GLYPH}"
AFFORDANCE = (" " + _DENY_AFFORDANCE).ljust(COLS - len(_ALLOW_AFFORDANCE)) + _ALLOW_AFFORDANCE

# ── Terminal-stub keys (phase 1 only; phase 2 replaces these with buttons) ──
KEY_ALLOW = "y"
KEY_DENY = "n"

# ── Serial link to the C3 keytag (phase 2a bring-up) ────────────────────────
SERIAL_BAUD = 115200
# A physical unplug kills the OS-level COM port handle; the reconnect on replug
# mirrors BLE's below.
SERIAL_RECONNECT_TRIES = 3
SERIAL_RECONNECT_BACKOFF_S = 1.5

# ── BLE link to the C3 keytag (phase 2b) ────────────────────────────────────
# Nordic UART Service: the same line protocol, carried over BLE characteristics.
BLE_DEVICE_NAME = "crabtag"
BLE_NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
BLE_NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # bridge -> keytag (write)
BLE_NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # keytag -> bridge (notify)
BLE_SCAN_TIMEOUT_S = 15.0
BLE_CHUNK = 20  # write frames in MTU-safe chunks; the keytag reassembles by newline
BLE_RECONNECT_TRIES = 3  # reconnect attempts before a prompt fails closed (deny)
BLE_RECONNECT_BACKOFF_S = 1.5

# ── WiFi / WebSocket link to the C3 keytag (phase 2c, "away" mode) ───────────
# The keytag is the client: it connects out to this endpoint (works behind a
# hotspot / NAT). It authenticates with a shared token (KEYTAG_TOKEN in the
# bridge's environment; baked into the firmware's secrets.h).
WS_PATH = "/keytag"
WS_CONNECT_WAIT_S = 10.0  # how long push_screen waits for the keytag to (re)connect

# ── Real plan-limit usage (the actual `/usage` command, not OTLP) ───────────
# There is no API/hook/OTLP metric for the real session/week plan-limit bars —
# `/usage` is an interactive-only command, so this polls it by shelling out to
# the real `claude` CLI. Keep this well above a few seconds: each poll is a
# real subprocess spawn plus a network round-trip to Anthropic's usage endpoint.
PLAN_USAGE_POLL_S = 300.0

# ── Tracing ────────────────────────────────────────────────────────────────
TRACE_PATH = "trace.jsonl"
