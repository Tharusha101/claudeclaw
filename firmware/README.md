# crabtag keytag firmware — phase 2a

ESP32-C3 mini + ILI9341 240×320 SPI display + three buttons. Renders frames the
bridge pushes over USB serial and reports button presses back. All layout lives
in `render.py` on the bridge; this firmware just draws lines and reads buttons.

> Assumes the **SPI** ILI9341 module (the one with a `CS/DC/RST/SDI/SCK/MISO`
> header). If yours is the 8-bit **parallel** Arduino shield, this pinout does
> not apply — say so before wiring.

Two build environments share `src/main.cpp`: `esp32` (classic WROOM-32 DevKit,
the bring-up board now) and `esp32-c3` (the eventual keytag MCU). Pick with `-e`.

## Wiring — ESP32 (WROOM-32 DevKit) — `-e esp32`

Display module → ESP32 (matches the `[env:esp32]` build flags):

| ILI9341 pin | ESP32 GPIO | note |
|---|---|---|
| VCC | 3V3 | if the screen stays blank/white, try VCC → 5V (VIN) instead |
| GND | GND | |
| CS | GPIO15 | |
| RESET | GPIO4 | |
| DC / RS | GPIO2 | strapping pin; if upload fails, briefly unplug DC during flash |
| SDI (MOSI) | GPIO23 | |
| SCK | GPIO18 | |
| LED | 3V3 | backlight always on (TFT_BL=-1) |
| SDO (MISO) | GPIO19 | optional for drawing — leave unconnected if you want |
| T_* (touch) | — | unused; leave unconnected |

Buttons — each between the GPIO and GND (internal pull-ups, active-low):

| Button | ESP32 GPIO |
|---|---|
| DENY (left) | GPIO25 |
| AUX (middle, reserved) | GPIO26 |
| ALLOW (right) | GPIO27 |

Do not use GPIO34–39 for buttons — they are input-only with no internal pull-up.

## Wiring — ESP32-C3 mini — `-e esp32-c3`

| ILI9341 | C3 GPIO | | Button | C3 GPIO |
|---|---|---|---|---|
| CS→7, RESET→3, DC→10 | | | DENY (left) | GPIO0 |
| SDI→6, SCK→4, MISO→5 | | | AUX (middle) | GPIO1 |
| LED→3V3, VCC→3V3 | | | ALLOW (right) | GPIO21 |

GPIO2/8/9 (strapping) and GPIO18/19 (native USB) are deliberately avoided.

## Build & flash

```sh
cd firmware
pio run -t upload          # default env is esp32; add -e esp32-c3 for the C3
pio device monitor         # expect "READY", then "BTN ..." lines on each press
```

On boot the screen shows `crabtag / waiting for bridge`. Then run the bridge
pointed at the board's serial port (`pio device list` shows it):

```sh
uv run python bridge.py --serial COM5      # your port; /dev/ttyUSB0 on Linux
```

A permission prompt from Claude Code now renders on the display; press DENY or
ALLOW and the decision flows back. AUX is wired but ignored for now.

## Protocol (for reference)

```
bridge -> C3 :  FRAME 8\n  then 8 lines, each exactly 20 ASCII chars
C3 -> bridge :  BTN ALLOW | BTN DENY | BTN AUX      (READY on boot)
```
