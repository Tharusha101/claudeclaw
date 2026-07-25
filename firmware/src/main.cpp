// crabtag keytag firmware — phase 2a bring-up.
//
// Speaks the bridge's serial wire protocol (see transport/serial_link.py):
//   in :  "FRAME 8\n" then 8 lines of <= 20 chars  -> draw the prompt.
//         "IDLE\n"                                  -> return to the crab face.
//   out:  "BTN ALLOW" / "BTN DENY" / "BTN AUX" on a press, "READY" on boot.
//
// Two display states:
//   IDLE   - two eyes on an orange background, alternating between black squares
//            and a happy ">  <" squint. Firmware-drawn; shown on boot too.
//   PROMPT - the 20x8 text frame from render.py, drawn verbatim at text size 1.
//
// Display: ST7735 1.8" 128x160 over software SPI (Adafruit_GFX), used in
// landscape (160x128). Module pins map LED/SCK/SDA/A0/RST/CS.

#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <Arduino.h>
#include <NimBLEDevice.h>
#include <SPI.h>

// Nordic UART Service: the line protocol over BLE. Bridge writes frames to RX,
// the keytag notifies button presses on TX. Same bytes as the serial link.
#define NUS_SERVICE "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
#define NUS_RX "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
#define NUS_TX "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

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

// Landscape geometry (after setRotation(1)).
constexpr int SCREEN_W = 160;
constexpr int SCREEN_H = 128;

constexpr int COLS = 20;
constexpr int ROWS = 8;
constexpr int MARGIN_X = 6;
constexpr int MARGIN_Y = 4;
constexpr int LINE_H = 15;  // 8 rows * 15 = 120, fits the 128 px landscape height

uint16_t CRAB;      // Claude-crab coral (header bar + idle background)
uint16_t DENY_COL;  // red deny button
uint16_t ALLOW_COL; // green allow button
uint16_t DIM;       // muted grey for secondary text
// all set in setup() via color565

enum class Mode { IDLE, PROMPT };
Mode mode = Mode::IDLE;

String frame[ROWS];

// ---- incoming serial: a tiny line-buffered state machine ----
String lineBuf;
int expectRows = 0;  // >0 while consuming a frame body
int rowIndex = 0;

// ================= idle eyes =================

constexpr int EYE_LX = 56, EYE_RX = 104, EYE_Y = 64;  // centred on the 160x128 screen
constexpr int EYE_HALF = 12;   // square eye half-size
constexpr int EYE_REACH = 11;  // ">  <" squint reach
constexpr int EYE_CLEAR = 16;  // half-size of the area wiped between eye states

bool blinking = false;
uint32_t blinkAt = 0;
uint32_t blinkUntil = 0;

void clearEyes() {
  tft.fillRect(EYE_LX - EYE_CLEAR, EYE_Y - EYE_CLEAR, 2 * EYE_CLEAR, 2 * EYE_CLEAR, CRAB);
  tft.fillRect(EYE_RX - EYE_CLEAR, EYE_Y - EYE_CLEAR, 2 * EYE_CLEAR, 2 * EYE_CLEAR, CRAB);
}

void drawEyesOpen() {  // two black squares (neutral)
  clearEyes();
  tft.fillRect(EYE_LX - EYE_HALF, EYE_Y - EYE_HALF, 2 * EYE_HALF, 2 * EYE_HALF, ST77XX_BLACK);
  tft.fillRect(EYE_RX - EYE_HALF, EYE_Y - EYE_HALF, 2 * EYE_HALF, 2 * EYE_HALF, ST77XX_BLACK);
}

void drawEyesSquint() {  // ">  <" happy squint
  clearEyes();
  const int e = EYE_REACH;
  for (int t = 0; t < 4; t++) {  // thickness
    // left ">"  (point toward centre)
    tft.drawLine(EYE_LX - e + t, EYE_Y - e, EYE_LX + e + t, EYE_Y, ST77XX_BLACK);
    tft.drawLine(EYE_LX + e + t, EYE_Y, EYE_LX - e + t, EYE_Y + e, ST77XX_BLACK);
    // right "<"  (point toward centre)
    tft.drawLine(EYE_RX + e - t, EYE_Y - e, EYE_RX - e - t, EYE_Y, ST77XX_BLACK);
    tft.drawLine(EYE_RX - e - t, EYE_Y, EYE_RX + e - t, EYE_Y + e, ST77XX_BLACK);
  }
}

void enterIdle() {
  mode = Mode::IDLE;
  blinking = false;
  tft.fillScreen(CRAB);  // orange background
  drawEyesOpen();
  blinkAt = millis() + 2500;
}

void animateIdle() {
  const uint32_t now = millis();
  if (!blinking && now >= blinkAt) {
    blinking = true;
    blinkUntil = now + 200;
    drawEyesSquint();
  } else if (blinking && now >= blinkUntil) {
    blinking = false;
    drawEyesOpen();
    blinkAt = now + 2200 + (uint32_t)random(0, 2800);
  }
}

// ================= prompt frame =================

// render.py's fixed row layout (see render.py): 0 header, 1 divider,
// 2-4 payload, 5 context, 6 divider, 7 affordance. The firmware styles it:
// the divider/affordance rows become graphical chrome, the rest is drawn verbatim.
void drawButton(int x, int y, int w, int h, uint16_t bg, const char* label) {
  tft.fillRoundRect(x, y, w, h, 4, bg);
  const int tx = x + (w - (int)strlen(label) * 6) / 2;
  const int ty = y + (h - 8) / 2;
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.setCursor(tx, ty);
  tft.print(label);
}

void drawFrame() {
  mode = Mode::PROMPT;
  tft.fillScreen(ST77XX_BLACK);
  tft.setTextSize(1);

  // header bar: tool name + queue depth (row 0), dark text on coral
  tft.fillRect(0, 0, SCREEN_W, 16, CRAB);
  tft.setTextColor(ST77XX_BLACK);
  tft.setCursor(5, 4);
  tft.print(frame[0]);

  // command payload (rows 2-4), white
  tft.setTextColor(ST77XX_WHITE);
  int y = 28;
  for (int r = 2; r <= 4; r++) {
    tft.setCursor(6, y);
    tft.print(frame[r]);
    y += 13;
  }

  // context (row 5), muted
  tft.setTextColor(DIM);
  tft.setCursor(6, 74);
  tft.print(frame[5]);

  // deny / allow buttons mirroring the physical left / right buttons
  drawButton(6, 104, 68, 20, DENY_COL, "DENY");
  drawButton(SCREEN_W - 6 - 68, 104, 68, 20, ALLOW_COL, "ALLOW");
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

// One byte of the FRAME/IDLE stream, from either serial or BLE, into the line
// buffer. Newline-framed, so it does not matter how BLE chunks the writes.
void feedByte(char c) {
  if (c == '\n') {
    handleLine(lineBuf);
    lineBuf = "";
  } else if (c != '\r') {
    lineBuf += c;
  }
}

void pollSerial() {
  while (Serial.available()) feedByte((char)Serial.read());
}

// ================= BLE (Nordic UART Service) =================

NimBLECharacteristic* txChar = nullptr;
bool bleConnected = false;

class RxCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* c) override {
    std::string v = c->getValue();
    for (char ch : v) feedByte(ch);
  }
};

class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer*) override { bleConnected = true; }
  void onDisconnect(NimBLEServer*) override {
    bleConnected = false;
    NimBLEDevice::startAdvertising();  // stay discoverable
  }
};

void setupBLE() {
  NimBLEDevice::init("crabtag");
  NimBLEServer* server = NimBLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  NimBLEService* svc = server->createService(NUS_SERVICE);
  NimBLECharacteristic* rx =
      svc->createCharacteristic(NUS_RX, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
  rx->setCallbacks(new RxCallbacks());
  txChar = svc->createCharacteristic(NUS_TX, NIMBLE_PROPERTY::NOTIFY);
  svc->start();

  NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
  adv->addServiceUUID(NUS_SERVICE);
  adv->setScanResponse(true);
  NimBLEDevice::startAdvertising();
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

void sendButton(const char* name) {
  Serial.print("BTN ");
  Serial.println(name);  // serial path (and handy debug)
  if (txChar != nullptr && bleConnected) {
    String msg = String("BTN ") + name + "\n";
    txChar->setValue((uint8_t*)msg.c_str(), msg.length());
    txChar->notify();
  }
}

void pollButtons() {
  uint32_t now = millis();
  for (Button& b : buttons) {
    bool pressed = digitalRead(b.pin) == LOW;
    if (pressed && !b.wasPressed && (now - b.lastEdge) > 40) {
      b.lastEdge = now;
      sendButton(b.name);
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
  tft.setRotation(1);         // landscape 160x128 (try 3 to flip 180°)
  CRAB = tft.color565(205, 92, 70);  // Claude coral (green pulled down; ST7735 renders green hot)
  DENY_COL = tft.color565(198, 58, 52);
  ALLOW_COL = tft.color565(58, 158, 92);
  DIM = tft.color565(150, 150, 150);

  setupBLE();
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
