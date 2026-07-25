// crabtag keytag firmware — phase 2a bring-up.
//
// Speaks the bridge's serial wire protocol (see transport/serial_link.py):
//   in :  "FRAME 8\n" then 8 lines of <= 20 chars  -> draw the prompt.
//         "IDLE\n"                                  -> return to the crab face.
//   out:  "BTN ALLOW" / "BTN DENY" / "BTN AUX" on a press, "READY" on boot.
//
// Two display states:
//   IDLE   - a Claude-crab face (orange, blinking eyes that glance around). Drawn
//            by the firmware; this is the one graphic it owns. Shown on boot too,
//            so the keytag looks alive even before the bridge connects.
//   PROMPT - the 20x8 text frame from render.py, drawn verbatim at text size 1.
//
// Display: ST7735 1.8" 128x160 over software SPI (Adafruit_GFX). Module pins map
// LED/SCK/SDA/A0/RST/CS -> backlight/clock/mosi/dc/reset/cs.

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

constexpr int SCREEN_W = 128;
constexpr int SCREEN_H = 160;

constexpr int COLS = 20;
constexpr int ROWS = 8;
constexpr int MARGIN_X = 4;
constexpr int MARGIN_Y = 8;
constexpr int LINE_H = 18;  // 8 rows * 18 = 144, fits the 160 px height

uint16_t CRAB;  // Claude-crab coral; set in setup() via color565

enum class Mode { IDLE, PROMPT };
Mode mode = Mode::IDLE;

String frame[ROWS];

// ---- incoming serial: a tiny line-buffered state machine ----
String lineBuf;
int expectRows = 0;  // >0 while consuming a frame body
int rowIndex = 0;

// ================= idle crab face =================

constexpr int EYE_Y = 62;
constexpr int EYE_LX = 40;
constexpr int EYE_RX = 88;
constexpr int EYE_R = 18;
constexpr int PUPIL_R = 8;

int pupilDX = 0;
int pupilDY = 0;
bool blinking = false;
uint32_t blinkAt = 0;     // when the next blink starts
uint32_t blinkUntil = 0;  // when the current blink ends

void drawEyesOpen() {
  tft.fillCircle(EYE_LX, EYE_Y, EYE_R, ST77XX_WHITE);
  tft.fillCircle(EYE_RX, EYE_Y, EYE_R, ST77XX_WHITE);
  tft.fillCircle(EYE_LX + pupilDX, EYE_Y + pupilDY, PUPIL_R, ST77XX_BLACK);
  tft.fillCircle(EYE_RX + pupilDX, EYE_Y + pupilDY, PUPIL_R, ST77XX_BLACK);
}

void drawEyesClosed() {
  // Wipe the eye area back to face colour, then a happy closed-eye line.
  tft.fillRect(EYE_LX - EYE_R, EYE_Y - EYE_R, 2 * EYE_R + 1, 2 * EYE_R + 1, CRAB);
  tft.fillRect(EYE_RX - EYE_R, EYE_Y - EYE_R, 2 * EYE_R + 1, 2 * EYE_R + 1, CRAB);
  tft.fillRect(EYE_LX - EYE_R + 3, EYE_Y - 2, 2 * EYE_R - 6, 4, ST77XX_WHITE);
  tft.fillRect(EYE_RX - EYE_R + 3, EYE_Y - 2, 2 * EYE_R - 6, 4, ST77XX_WHITE);
}

void drawSmile() {
  const int cx = SCREEN_W / 2;
  const int my = EYE_Y + EYE_R + 16;
  for (int t = 0; t < 2; t++) {  // 2 px thick
    tft.drawLine(cx - 14, my - 3 + t, cx - 6, my + 3 + t, ST77XX_WHITE);
    tft.drawLine(cx - 6, my + 3 + t, cx + 6, my + 3 + t, ST77XX_WHITE);
    tft.drawLine(cx + 6, my + 3 + t, cx + 14, my - 3 + t, ST77XX_WHITE);
  }
}

void enterIdle() {
  mode = Mode::IDLE;
  pupilDX = 0;
  pupilDY = 0;
  blinking = false;
  tft.fillScreen(CRAB);
  drawEyesOpen();
  drawSmile();
  blinkAt = millis() + 2500;
}

void animateIdle() {
  const uint32_t now = millis();
  if (!blinking && now >= blinkAt) {
    blinking = true;
    blinkUntil = now + 130;
    drawEyesClosed();
  } else if (blinking && now >= blinkUntil) {
    blinking = false;
    pupilDX = (int)random(-7, 8);  // glance somewhere new after each blink
    pupilDY = (int)random(-4, 5);
    drawEyesOpen();
    blinkAt = now + 2200 + (uint32_t)random(0, 2600);
  }
}

// ================= prompt frame =================

void drawFrame() {
  mode = Mode::PROMPT;
  tft.fillScreen(ST77XX_BLACK);
  tft.setTextSize(1);  // 6x8 font; 20 cols * 6 = 120 px, fits the 128 px width
  for (int r = 0; r < ROWS; r++) {
    uint16_t colour = ST77XX_WHITE;
    if (r == 0) {
      colour = CRAB;  // tool-name row in the crab colour
    } else if (r == ROWS - 1) {
      colour = ST77XX_GREEN;  // affordance row
    }
    tft.setTextColor(colour, ST77XX_BLACK);
    tft.setCursor(MARGIN_X, MARGIN_Y + r * LINE_H);
    tft.print(frame[r]);
  }
}

// ================= serial in =================

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
  } else if (line == "IDLE") {
    enterIdle();
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

// ================= buttons =================

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

  randomSeed(micros());

  tft.initR(INITR_BLACKTAB);  // 1.8" 128x160; if colors/edges look off, try INITR_GREENTAB
  tft.setRotation(0);         // portrait 128x160
  CRAB = tft.color565(217, 119, 87);  // Claude coral

  enterIdle();
  Serial.println("READY");
}

void loop() {
  pollSerial();
  pollButtons();
  if (mode == Mode::IDLE) {
    animateIdle();
  }
}
