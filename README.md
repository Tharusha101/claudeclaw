# crabtag

A bridge daemon connecting Claude Code to a physical keychain device — an
ESP32-C3 board shaped like the Claude Code crab, with a 240×240-class TFT
(actual panel: ST7735 1.8", 128×160) and three buttons. The keytag shows what
Claude Code is doing and lets you approve or deny permission prompts without
touching your phone.

```
Claude Code ──HTTP hooks──▶ bridge ──transport──▶ keytag
Claude Code ──OTLP─────────▶ bridge                  │
                              ▲                       │
                              └──── allow / deny ─────┘
```

See `CLAUDE.md` for the full design rationale, wire protocol, and the "why"
behind every non-obvious decision in this codebase.

## Status

Four link modes, all speaking the same line protocol, one firmware source:

| Mode | Flag | Notes |
|---|---|---|
| Terminal stub | *(default)* | No hardware. Prints the screen, reads a keypress. |
| USB serial | `--serial COM5` | Direct cable to the C3. |
| BLE | `--ble` | Keytag ↔ bridge direct, no phone, no cable. |
| WiFi / WebSocket | `--ws` | "Away" mode — keytag joins a hotspot and connects out over `wss`, works behind NAT. Hardened with a named Cloudflare tunnel; see `tunnel/`. |

On top of approve/deny, the keytag also shows:
- **Idle-face moods** (awake, sleepy, focused, dizzy, and a couple of easter
  eggs) that mirror Claude Code's hook events in real time.
- **A cost/token meter** against a budget you set, fed by Claude Code's native
  OTLP export.
- **Real plan-limit usage** (session/week %, the actual numbers behind
  Claude Code's `/usage` command) — see the Cost tracking section of
  `CLAUDE.md` for how, since there's no supported API for this.

## Run it

```sh
uv sync

uv run python bridge.py                 # terminal stub, no hardware needed
uv run python bridge.py --serial COM5   # real keytag over USB
uv run python bridge.py --ble           # real keytag over BLE
uv run python bridge.py --ws            # real keytag over WiFi (needs KEYTAG_TOKEN)
```

`.claude/settings.json` already points Claude Code's hooks at
`http://localhost:8787`, so with the bridge running, a real tool prompt shows
up on whichever transport you picked.

Firmware lives in `firmware/` (PlatformIO). Build/flash target depends on the
link:

```sh
cd firmware
pio run -e esp32-c3 -t upload --upload-port COM5        # BLE + serial build
pio run -e esp32-c3-wifi -t upload --upload-port COM5   # WiFi build (needs secrets.h)
```

## Checks

```sh
uv run pytest            # everything
uv run pytest -m smoke   # end-to-end bridge smoke test
uv run ruff check .
uv run mypy .
```

Every hook event is appended to `trace.jsonl` (gitignored).
