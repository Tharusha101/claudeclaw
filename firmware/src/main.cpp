// crabtag keytag firmware — phase 2a bring-up.
//
// Speaks the bridge's serial wire protocol (see transport/serial_link.py):
//   in :  "FRAME 8\n" then 8 lines of <= 20 chars -> draw them verbatim.
//   out:  "BTN ALLOW" / "BTN DENY" / "BTN AUX" on a press, "READY" on boot.
//
// Display: ST7735 1.8" 128x160 over *software* SPI via Adafruit_GFX. Module pins
// map LED/SCK/SDA/A0/RST/CS -> backlight/clock/mosi/dc/reset/cs. Software SPI
// bit-bangs on the given GPIOs — slower than hardware SPI, but rock-solid on the
// ESP32-C3, and our redraw rate is far too low to care. All layout/formatting is
// decided by render.py on the bridge; this firmware only draws what it is handed:
// the same 20x8 frame, just rendered at text size 1 so 20 chars fit in 128 px.

#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <Arduino.h>
#include <SPI.h>

// Pins come from build flags (see platformio.ini) so one source serves both boards.
// A0 on the module is DC; SDA is MOSI.
#ifndef PIN_TFT_CS
#define PIN_TFT_CS 7
#endif
#ifndef PIN_TFT_DC
#define PIN_TFT_DC 10
#endif
#ifndef PIN_TFT_RST
#define PIN_TFT_RST 3
#endif
#ifndef PIN_TFT_MOSI
#define PIN_TFT_MOSI 6
#endif
#ifndef PIN_TFT_SCLK
#define PIN_TFT_SCLK 4
#endif

// Buttons, active-low with internal pull-ups. Left = deny, right = allow,
// mirroring the on-screen "x deny ... allow v" affordance; middle = aux (reserved).
#ifndef BTN_DENY_PIN
#define BTN_DENY_PIN 0
#endif
#ifndef BTN_AUX_PIN
#define BTN_AUX_PIN 1
#endif
#ifndef BTN_ALLOW_PIN
#define BTN_ALLOW_PIN 21
#endif

// Software SPI constructor: (cs, dc, mosi, sclk, rst). ST7735 is write-only (no miso).
Adafruit_ST7735 tft(PIN_TFT_CS, PIN_TFT_DC, PIN_TFT_MOSI, PIN_TFT_SCLK, PIN_TFT_RST);

constexpr uint8_t PIN_DENY = BTN_DENY_PIN;
constexpr uint8_t PIN_AUX = BTN_AUX_PIN;
constexpr uint8_t PIN_ALLOW = BTN_ALLOW_PIN;

constexpr int COLS = 20;
constexpr int ROWS = 8;
constexpr int MARGIN_X = 4;
constexpr int MARGIN_Y = 8;
constexpr int LINE_H = 18;  // 8 rows * 18 = 144, fits the 160 px height

String frame[ROWS];

// ---- incoming serial: a tiny line-buffered state machine ----
String lineBuf;
int expectRows = 0;  // >0 while consuming a frame body
int rowIndex = 0;

void drawFrame() {
  tft.fillScreen(ST77XX_BLACK);
  tft.setTextSize(1);  // 6x8 font; 20 cols * 6 = 120 px, fits the 128 px width
  for (int r = 0; r < ROWS; r++) {
    // Highlight the affordance row (last) so the buttons read at a glance.
    tft.setTextColor(r == ROWS - 1 ? ST77XX_GREEN : ST77XX_WHITE, ST77XX_BLACK);
    tft.setCursor(MARGIN_X, MARGIN_Y + r * LINE_H);
    tft.print(frame[r]);
  }
}

void handleLine(const String& line) {
  if (expectRows > 0) {
    if (rowIndex < ROWS) frame[rowIndex] = line;
    rowIndex++;
    if (rowIndex >= expectRows) {
      expectRows = 0;
      drawFrame();
    }
    return;
  }
  if (line.startsWith("FRAME ")) {
    int n = line.substring(6).toInt();
    if (n < 1) n = 1;
    if (n > ROWS) n = ROWS;
    expectRows = n;
    rowIndex = 0;
  }
}

void pollSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      handleLine(lineBuf);
      lineBuf = "";
    } else if (c != '\r') {
      lineBuf += c;
    }
  }
}

// ---- buttons with a simple debounce on the falling edge ----
struct Button {
  uint8_t pin;
  const char* name;
  bool wasPressed;
  uint32_t lastEdge;
};

Button buttons[] = {
    {PIN_DENY, "DENY", false, 0},
    {PIN_ALLOW, "ALLOW", false, 0},
    {PIN_AUX, "AUX", false, 0},
};

void pollButtons() {
  uint32_t now = millis();
  for (Button& b : buttons) {
    bool pressed = digitalRead(b.pin) == LOW;
    if (pressed && !b.wasPressed && (now - b.lastEdge) > 40) {
      b.lastEdge = now;
      Serial.print("BTN ");
      Serial.println(b.name);
    }
    b.wasPressed = pressed;
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_DENY, INPUT_PULLUP);
  pinMode(PIN_AUX, INPUT_PULLUP);
  pinMode(PIN_ALLOW, INPUT_PULLUP);

  tft.initR(INITR_BLACKTAB);  // 1.8" 128x160; if colors/edges look off, try INITR_GREENTAB
  tft.setRotation(0);         // portrait 128x160
  tft.fillScreen(ST77XX_BLACK);

  frame[0] = "crabtag";
  frame[2] = "waiting for bridge";
  drawFrame();

  Serial.println("READY");
}

void loop() {
  pollSerial();
  pollButtons();
}
