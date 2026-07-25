// crabtag keytag firmware — phase 2a bring-up.
//
// Speaks the bridge's serial wire protocol (see transport/serial_link.py):
//   in :  "FRAME 8\n" then 8 lines of <= 20 chars -> draw them verbatim.
//   out:  "BTN ALLOW" / "BTN DENY" / "BTN AUX" on a button press, "READY" on boot.
//
// All layout/formatting is decided by render.py on the bridge; this firmware
// only draws the lines it is handed and reports button presses.

#include <Arduino.h>
#include <TFT_eSPI.h>

TFT_eSPI tft = TFT_eSPI();

// Buttons, active-low with internal pull-ups. Left = deny, right = allow,
// mirroring the on-screen "x deny ... allow v" affordance; middle = aux (reserved).
// Pins come from build flags (see platformio.ini) so one source serves both boards.
#ifndef BTN_DENY_PIN
#define BTN_DENY_PIN 0
#endif
#ifndef BTN_AUX_PIN
#define BTN_AUX_PIN 1
#endif
#ifndef BTN_ALLOW_PIN
#define BTN_ALLOW_PIN 21
#endif

constexpr uint8_t PIN_DENY = BTN_DENY_PIN;
constexpr uint8_t PIN_AUX = BTN_AUX_PIN;
constexpr uint8_t PIN_ALLOW = BTN_ALLOW_PIN;

constexpr int COLS = 20;
constexpr int ROWS = 8;

constexpr int MARGIN_X = 6;
constexpr int MARGIN_Y = 8;
constexpr int LINE_H = 24;  // 8 rows * 24 = 192 px, fits the 320 px height

String frame[ROWS];

// ---- incoming serial: a tiny line-buffered state machine ----
String lineBuf;
int expectRows = 0;  // >0 while consuming a frame body
int rowIndex = 0;

void drawFrame() {
  tft.fillScreen(TFT_BLACK);
  for (int r = 0; r < ROWS; r++) {
    // Highlight the affordance row (last) so the buttons read at a glance.
    tft.setTextColor(r == ROWS - 1 ? TFT_GREEN : TFT_WHITE, TFT_BLACK);
    tft.drawString(frame[r], MARGIN_X, MARGIN_Y + r * LINE_H, 2);
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

  tft.init();
  tft.setRotation(0);  // portrait 240x320
  tft.fillScreen(TFT_BLACK);

  frame[0] = "crabtag";
  frame[2] = "waiting for bridge";
  drawFrame();

  Serial.println("READY");
}

void loop() {
  pollSerial();
  pollButtons();
}
