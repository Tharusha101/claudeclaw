# crabtag keytag firmware

ESP32-C3 mini + ST7735 1.8" 128×160 SPI display + three buttons. Renders frames
the bridge pushes over USB serial and reports button presses back. All layout
lives in `render.py` on the bridge; the firmware draws the same 20×8 frame at
text size 1 so it fits 128 px wide.

> Display driver is **ST7735** (module pins `LED/SCK/SDA/A0/RST/CS/GND/VCC`,
> where `SDA`=MOSI and `A0`=DC). Init uses `INITR_BLACKTAB`; if colors or edges
> look off, try `INITR_GREENTAB` / `INITR_REDTAB` in `src/main.cpp`.

Two build environments share `src/main.cpp`: `esp32-c3` (the board in use, and
the default) and `esp32` (classic WROOM-32 DevKit fallback). Pick with `-e`.

## Wiring — ESP32-C3 mini — `-e esp32-c3` (default)

| Display pin | C3 GPIO | note |
|---|---|---|
| VCC | 3V3 | if the screen stays dark, try VCC → 5V |
| GND | GND | |
| LED | 3V3 | backlight always on |
| SCK | GPIO4 | |
| SDA (MOSI) | GPIO6 | |
| A0 (DC) | GPIO10 | |
| RST | GPIO3 | |
| CS | GPIO7 | |

Buttons — each between the GPIO and GND (internal pull-ups, active-low):

| Button | C3 GPIO |
|---|---|
| DENY (left) | GPIO0 |
| AUX (middle, reserved) | GPIO1 |
| ALLOW (right) | GPIO21 |

GPIO2/8/9 (strapping) and GPIO18/19 (native USB) are deliberately avoided.

## Wiring — ESP32 (WROOM-32 DevKit) — `-e esp32`

Same display pins remapped to GPIO ≤21 (avoiding flash pins 6–11, UART 1/3):
SCK→14, SDA→13, A0→2, RST→4, CS→5, LED/VCC→3V3. Buttons: DENY→16, AUX→17,
ALLOW→21. (Do not use GPIO34–39 for buttons — input-only, no pull-up.)

## Build & flash

```sh
cd firmware
pio run -t upload          # default env is esp32-c3; add -e esp32 for the WROOM
pio device monitor         # expect "READY", then "BTN ..." lines on each press
```

On boot the screen shows the idle **crab eyes** (on coral). The link is chosen at
build time:

| Build env | Link | Bridge |
|---|---|---|
| `esp32-c3` (default) | BLE ("home") | `uv run python bridge.py --ble` |
| `esp32-c3-wifi` | WiFi/WebSocket ("away") | `KEYTAG_TOKEN=... uv run python bridge.py --ws` |
| — | USB serial (any build) | `uv run python bridge.py --serial COM5` |

All three carry the same `FRAME`/`IDLE`/`BTN` line protocol.

### WiFi build ("away" mode)

Copy `src/secrets.h.example` to `src/secrets.h` (gitignored) and fill in your
WiFi/hotspot SSID + password, a long random `KEYTAG_TOKEN`, and the bridge's
host/port as reachable from the keytag. Then:

```sh
pio run -e esp32-c3-wifi -t upload
KEYTAG_TOKEN=<same-token> uv run python bridge.py --ws   # on the PC
```

The keytag joins WiFi and opens a WebSocket to the bridge, authenticating with
the token. The bridge **rejects any connection without the matching token** —
this channel carries the approval decision, so an unauthenticated peer must
never be able to send one.

- **LAN test:** `BRIDGE_HOST` = your PC's IP, `BRIDGE_PORT` = 8787, `BRIDGE_TLS` = 0,
  and run the bridge with `--ws --lan` (the `--lan` opts the bridge onto the LAN).
- **Quick tunnel (throwaway proof):** `cloudflared tunnel --url http://localhost:8787`
  → set `BRIDGE_HOST` = the printed `*.trycloudflare.com`, `BRIDGE_PORT` = 443,
  `BRIDGE_TLS` = 1. Run the bridge with just `--ws` (localhost). Note: a quick
  tunnel exposes the *whole* bridge and its URL changes on restart.
- **Named tunnel (the hardened "away" setup):** stable host, only `/keytag`
  exposed, validated cert. See **`../tunnel/README.md`**.

The bridge binds **localhost** for `--ws` (a tunnel reaches it there), keeping it
off the LAN — use `--lan` only for the direct-WiFi test. Set `BRIDGE_CA_CERT` in
`secrets.h` to validate the tunnel's cert (otherwise wss is encrypted but
unvalidated — fine on trusted WiFi, risky on public networks).

A permission prompt from Claude Code flips the display to the text frame; press
DENY or ALLOW and the decision flows back, then the display returns to the crab
face. AUX is wired but ignored for now.

## Display states

- **IDLE** — the crab face, drawn and animated by the firmware. Shown on boot and
  whenever no prompt is pending.
- **PROMPT** — the 20×8 text frame from `render.py`, drawn verbatim.

## Protocol (for reference)

```
bridge -> C3 :  FRAME 8\n  then 8 lines, each exactly 20 ASCII chars   (show prompt)
                IDLE\n                                                 (show crab face)
C3 -> bridge :  BTN ALLOW | BTN DENY | BTN AUX      (READY on boot)
```
