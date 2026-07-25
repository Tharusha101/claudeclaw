# crabtag keytag firmware — phase 2a

ESP32-C3 mini + ILI9341 240×320 SPI display + three buttons. Renders frames the
bridge pushes over USB serial and reports button presses back. All layout lives
in `render.py` on the bridge; this firmware just draws lines and reads buttons.

> Assumes the **SPI** ILI9341 module (the one with a `CS/DC/RST/SDI/SCK/MISO`
> header). If yours is the 8-bit **parallel** Arduino shield, this pinout does
> not apply — say so before wiring.

## Wiring

Display module → C3 (matches `platformio.ini` build flags):

| ILI9341 pin | C3 GPIO | note |
|---|---|---|
| VCC | 3V3 | 5V also fine if the module has a regulator; SPI logic stays 3.3 V |
| GND | GND | |
| CS | GPIO7 | |
| RESET | GPIO3 | |
| DC / RS | GPIO10 | |
| SDI (MOSI) | GPIO6 | |
| SCK | GPIO4 | |
| LED | 3V3 | backlight always on (TFT_BL=-1) |
| SDO (MISO) | GPIO5 | optional for drawing — leave unconnected if you want |
| T_* (touch) | — | unused; leave unconnected |

Buttons — each between the GPIO and GND (internal pull-ups, active-low):

| Button | C3 GPIO |
|---|---|
| DENY (left) | GPIO0 |
| AUX (middle, reserved) | GPIO1 |
| ALLOW (right) | GPIO21 |

GPIO2, GPIO8, GPIO9 are C3 strapping pins and are deliberately avoided. GPIO18/19
are the native-USB D-/D+ lines — do not use them.

## Build & flash

```sh
cd firmware
pio run                 # build
pio run -t upload       # flash (put the C3 in bootloader mode if needed)
pio device monitor      # watch: you should see "READY", and BTN lines on press
```

On boot the screen shows `crabtag / waiting for bridge`. Then run the bridge
pointed at the C3's serial port:

```sh
uv run python bridge.py --serial COM5      # your port; /dev/ttyACM0 on Linux
```

A permission prompt from Claude Code now renders on the display; press DENY or
ALLOW and the decision flows back. AUX is wired but ignored for now.

## Protocol (for reference)

```
bridge -> C3 :  FRAME 8\n  then 8 lines, each exactly 20 ASCII chars
C3 -> bridge :  BTN ALLOW | BTN DENY | BTN AUX      (READY on boot)
```
