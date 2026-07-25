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

# ── Tracing ────────────────────────────────────────────────────────────────
TRACE_PATH = "trace.jsonl"
