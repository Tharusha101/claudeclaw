# CLAUDE.md — crabtag

## What this is

A bridge daemon connecting Claude Code to a physical keychain device: an ESP32-C3 board shaped like the Claude Code crab, with a 240×240 TFT and three buttons. The keytag shows what Claude Code is doing and lets me approve or deny permission prompts without taking my phone out.

This repo is the bridge, plus (from phase 2a) the C3 bring-up firmware under `firmware/`. The Android relay app is still a separate, later phase — do not scaffold it.

## Status: phase 2b (BLE direct) — done, hardware-verified

Phase 1 proved the loop with no hardware: a terminal stub printing the screen and reading a keypress from stdin. It is done and stays as the default transport.

Phase 2a put a real display in the loop over USB serial. The hardware is an **ESP32-C3 mini + ST7735 1.8" 128×160 SPI display + three physical buttons** (the panel the listing sold as ILI9341 is actually an ST7735; all formatting is in `render.py` so the same 20×8 frame retargets any panel). The idle screen is a firmware-drawn Claude-crab face (two eyes on coral); a prompt flips to a styled card with DENY/ALLOW buttons; `IDLE` returns to the face.

Phase 2b makes the link **BLE** (`transport/ble_link.py`), keytag ↔ bridge direct, no phone. Same line protocol carried over the Nordic UART Service; the firmware is both a serial and BLE endpoint, so `--serial` and `--ble` both work with one build. Verified end-to-end over Bluetooth on real hardware.

Order: 2a serial ✓ → 2b BLE direct ✓ → **2c WiFi/WebSocket ("away") ✓**. 2c replaces the original BLE-phone-relay idea: the keytag joins WiFi (a phone's Personal Hotspot when out — no app, works with any phone incl. iPhone) and opens a token-authenticated WebSocket to the bridge (`transport/ws_link.py`, firmware env `esp32-c3-wifi`). The bridge rejects any keytag connection without the shared `KEYTAG_TOKEN` — that channel carries the approval decision. Verified end-to-end on hardware over the LAN **and over the public internet via a Cloudflare quick tunnel** (`wss`). One firmware source, link chosen at build time (BLE vs `-D KEYTAG_WIFI`), TLS via `BRIDGE_TLS`.

Known gaps before daily "away" use (all documented in firmware/README): quick-tunnel URL is ephemeral (→ named tunnel needs a domain); the quick tunnel exposes the unauthenticated `/hooks` too (→ ingress-limit to `/keytag` or add hook auth); `beginSSL` encrypts but does not validate the cert (→ pin the CA). These are hardening steps, not blockers to the proven loop.

## Architecture

```
Claude Code ──HTTP hooks──▶ bridge ──transport──▶ keytag (terminal stub)
Claude Code ──OTLP─────────▶ bridge                    │
                              ▲                        │
                              └──── allow / deny ──────┘
```

## Layout

```
config.py        tunables only; no logic, no imports from other project modules
models.py        frozen dataclasses for events, approvals, cost snapshots
hooks.py         HTTP endpoints for Claude Code hook events
otlp.py          OTLP/HTTP metrics receiver
approvals.py     pure: pending-approval state machine
render.py        pure: event -> list[str] of screen lines
transport/
  base.py        abstract Transport (push_screen, await_decision)
  terminal.py    phase 1 implementation
bridge.py        wiring and entrypoint
tests/
```

Keep `approvals.py` and `render.py` free of I/O, async, and framework imports so they test without a server running.

## Claude Code integration facts

Verified against the current hooks reference. Don't guess at these shapes. If something looks wrong, check https://code.claude.com/docs/en/hooks rather than inventing a schema.

Hooks are configured in `.claude/settings.json` using `"type": "http"` handlers. The event JSON arrives as the POST body. The response body uses the same JSON output schema as command hooks.

Events consumed:

| Event | Purpose |
|---|---|
| `PermissionRequest` | the approve/deny flow — holds until the user answers |
| `Stop` | turn finished; carries `last_assistant_message` |
| `Notification` | matchers `idle_prompt`, `agent_needs_input`, `agent_completed` |
| `StopFailure` | error states; matcher carries `rate_limit`, `overloaded`, and similar |

Every event includes `session_id`, `cwd`, `transcript_path`, and `hook_event_name`.

A `PermissionRequest` decision is returned as:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": { "behavior": "deny" }
  }
}
```

`behavior` is `"allow"` or `"deny"`.

### Fail closed — this is the important one

For HTTP hooks, non-2xx responses, connection failures, and timeouts are all **non-blocking errors: execution continues**. A bridge that crashes or hangs therefore silently lets tool calls through.

So a `PermissionRequest` handler must never fall off the end without returning a decision. Both the exception path and the internal timeout path return an explicit `deny`. The internal timeout must be comfortably shorter than the hook's configured `timeout` (the default is 600s for http handlers), so the bridge answers rather than the hook giving up.

Return HTTP 200 on every path including deny. Parse the request body raw so framework validation cannot reject it before the handler runs. A Pydantic body model that 422s on a malformed payload is a fail-*open* trap: the non-2xx is a non-blocking error, so the tool proceeds. Even a deny is a 200 with the deny body.

## Cost tracking

Claude Code exports OpenTelemetry natively, gated on `CLAUDE_CODE_ENABLE_TELEMETRY=1`. Set `OTEL_METRICS_EXPORTER=otlp` and point `OTEL_EXPORTER_OTLP_ENDPOINT` at `http://localhost:4318`, which is the bridge. Read `claude_code.cost.usage` (estimated USD per API request) and `claude_code.token.usage` (input, output, cache-read, cache-creation). No collector needed — the bridge is the receiver.

## Screen constraints

The real display is 240×240. Assume **20 columns × 8 rows** of usable text.

All formatting happens here in Python, never in firmware. `render.py` emits at most 8 lines of at most 20 characters each, and the device draws them verbatim. Iterating on layout must never require reflashing a board.

Truncate long commands from the **middle**, not the end. The dangerous parts of `rm -rf /home/tharu/proj/build` live at both ends: `rm -rf …/build` is a useful approval prompt, `rm -rf /home/tharu…` is not.

## Conventions

- Python 3.11+, FastAPI, `uv` for dependencies.
- Config lives in `config.py` as module constants. No magic numbers anywhere else. `DECISION_TIMEOUT_S = 120` — a timeout-deny is cheap (Claude tells me, I re-run); a silently frozen agent, and on real hardware five minutes of lit screen and live radio, is not.
- Dataclasses over dicts for anything crossing a module boundary.
- Type hints throughout. `ruff` and `mypy` clean before a change counts as done.
- Log every hook event to a JSONL trace file. Debugging this is otherwise miserable.

## Testing

Every change ships with a test. Pure modules get unit tests. The server gets an end-to-end smoke test that fires a synthetic `PermissionRequest` at a running bridge, answers it through an injected fake transport, and asserts the returned JSON matches the documented shape.

`uv run pytest -m smoke` passes before any work is called finished.

## Don't

- Don't add BLE, WebSocket, or mobile code yet.
- Don't auto-approve anything, ever, for any reason, including in tests. Tests supply an explicit decision.
- Don't put formatting logic in the transport layer.
- Don't swallow exceptions in hook handlers. Log, then deny.
