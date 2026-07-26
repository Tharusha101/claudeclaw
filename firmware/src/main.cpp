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
#include <SPI.h>

// The link is chosen at build time: KEYTAG_WIFI -> WiFi/WebSocket ("away"),
// otherwise BLE ("home"). The display, buttons, and line parser are shared.
#ifdef KEYTAG_WIFI
#include <WebSocketsClient.h>
#include <WiFi.h>

#include "secrets.h"  // WIFI_SSID / WIFI_PASS / KEYTAG_TOKEN / BRIDGE_HOST / BRIDGE_PORT
#else
#include <NimBLEDevice.h>
// Nordic UART Service: the line protocol over BLE. Bridge writes frames to RX,
// the keytag notifies button presses on TX. Same bytes as the serial link.
#define NUS_SERVICE "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
#define NUS_RX "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
#define NUS_TX "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
#endif

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

// Onboard status LED (C3 SuperMini = GPIO8, active-low). Set to -1 to disable.
#ifndef LED_PIN
#define LED_PIN -1
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

enum class Mode { IDLE, PROMPT, USAGE };
Mode mode = Mode::IDLE;

String frame[ROWS];

// usage meter (set by the bridge's USAGE command; not currently shown on any
// screen, kept for a future affordance -- the real plan bars below replaced it
// as the usage screen's headline content)
float usageCost = 0;
long usageTokens = 0;
int usagePct = 0;

// real plan-limit usage (set by the bridge's PLAN command, itself sourced from
// the actual `claude` /usage command). -1 = not yet known.
int planSessionPct = -1;
int planWeekPct = -1;

// ---- incoming serial: a tiny line-buffered state machine ----
String lineBuf;
int expectRows = 0;  // >0 while consuming a frame body
int rowIndex = 0;

// ================= idle moods =================
// The idle face is one of several moods the bridge sets to mirror Claude Code:
// sleepy when idle, focused mid-turn, wide-eyed + claws on a prompt, dizzy when
// rate-limited, party on a long clean finish.

constexpr int EYE_LX = 56, EYE_RX = 104, EYE_Y = 64;  // centred on the 160x128 screen
constexpr int EYE_HALF = 12;

enum class Mood { AWAKE, SLEEPY, FOCUS, DIZZY, SMOKE, COOK };
Mood mood = Mood::AWAKE;

bool blinking = false;
uint32_t blinkAt = 0, blinkUntil = 0, animAt = 0;
float dizzySpin = 0;
int smokePhase = 0;

// Wipe the whole face band to orange (moods draw beyond the eye boxes).
void wipeFace() { tft.fillRect(0, EYE_Y - 34, SCREEN_W, 74, CRAB); }

void eyeSquare(int cx) {
  tft.fillRect(cx - EYE_HALF, EYE_Y - EYE_HALF, 2 * EYE_HALF, 2 * EYE_HALF, ST77XX_BLACK);
}
void eyeSquint(int cx, bool right) {  // ">" / "<"
  const int e = 11;
  for (int t = 0; t < 4; t++) {
    int s = right ? -1 : 1;
    tft.drawLine(cx - s * e + t * s, EYE_Y - e, cx + s * e + t * s, EYE_Y, ST77XX_BLACK);
    tft.drawLine(cx + s * e + t * s, EYE_Y, cx - s * e + t * s, EYE_Y + e, ST77XX_BLACK);
  }
}
void eyeSleepy(int cx) {  // half-lidded: lower half + a droopy lid line
  tft.fillRect(cx - EYE_HALF, EYE_Y + 2, 2 * EYE_HALF, EYE_HALF - 2, ST77XX_BLACK);
  tft.fillRect(cx - EYE_HALF - 2, EYE_Y - 1, 2 * EYE_HALF + 4, 3, ST77XX_BLACK);
}
void eyeFlat(int cx) {  // fully shut (blink)
  tft.fillRect(cx - EYE_HALF - 2, EYE_Y - 1, 2 * EYE_HALF + 4, 3, ST77XX_BLACK);
}
void eyeFocus(int cx, bool right) {  // narrowed, angled inward-down = concentrating
  for (int t = 0; t < 5; t++) {
    if (!right) tft.drawLine(cx - EYE_HALF, EYE_Y - 4 + t, cx + EYE_HALF, EYE_Y + 4 + t, ST77XX_BLACK);
    else        tft.drawLine(cx - EYE_HALF, EYE_Y + 4 + t, cx + EYE_HALF, EYE_Y - 4 + t, ST77XX_BLACK);
  }
}
void eyeSpiral(int cx, float spin) {
  for (int i = 0; i < 42; i++) {
    float a = i * 0.55f + spin, r = i * 0.30f;
    tft.fillRect(cx + (int)(r * cosf(a)), EYE_Y + (int)(r * sinf(a)), 2, 2, ST77XX_BLACK);
  }
}
// ---- props drawn on the full orange face (no body, no black background) ----
void drawBarEyes(int hw, int hh) {  // two vertical eyes on the face
  tft.fillRect(EYE_LX - hw, EYE_Y - hh, 2 * hw, 2 * hh, ST77XX_BLACK);
  tft.fillRect(EYE_RX - hw, EYE_Y - hh, 2 * hw, 2 * hh, ST77XX_BLACK);
}
// Rising puffs, animated by `phase`. Drawn (and wiped) in a column by animateMood.
void drawSmoke(int x, int baseY, int phase) {
  const uint16_t sm = tft.color565(225, 225, 225);
  for (int i = 0; i < 4; i++) {
    int p = (phase + i * 8) % 32;
    tft.fillRect(x + (((p / 5) % 2) ? 3 : -1), baseY - p, 4, 4, sm);
  }
}
void drawCigarette() {  // in the mouth area (smoke is animated separately)
  const int cy = 100;
  tft.fillRect(74, cy, 38, 6, ST77XX_WHITE);              // stick
  tft.fillRect(74, cy, 9, 6, tft.color565(150, 95, 55));  // filter
  tft.fillRect(108, cy, 4, 6, ST77XX_RED);                // lit tip
}
void drawChefHat() {  // white hat across the top of the face
  tft.fillRoundRect(44, 2, 72, 22, 9, ST77XX_WHITE);  // puffy top
  tft.fillRect(52, 22, 56, 12, ST77XX_WHITE);         // band
  const uint16_t g = tft.color565(205, 205, 205);
  for (int i = 0; i < 4; i++) tft.drawFastVLine(62 + i * 12, 24, 8, g);
}
void drawPan() {  // frying pan across the bottom, food (steam is animated separately)
  const int px = 90, py = 104;
  const uint16_t dark = tft.color565(40, 40, 45);
  tft.fillRoundRect(px, py, 44, 16, 7, dark);
  tft.fillRect(px + 42, py + 5, 24, 5, dark);  // handle
  tft.fillRect(px + 9, py + 4, 4, 4, ST77XX_RED);
  tft.fillRect(px + 20, py + 5, 4, 4, ST77XX_GREEN);
  tft.fillRect(px + 31, py + 4, 4, 4, ST77XX_YELLOW);
}

void drawMoodBase() {
  switch (mood) {
    case Mood::AWAKE:  eyeSquare(EYE_LX); eyeSquare(EYE_RX); break;
    case Mood::SLEEPY: eyeSleepy(EYE_LX); eyeSleepy(EYE_RX); break;
    case Mood::FOCUS:  eyeFocus(EYE_LX, false); eyeFocus(EYE_RX, true); break;
    case Mood::DIZZY:  eyeSpiral(EYE_LX, dizzySpin); eyeSpiral(EYE_RX, -dizzySpin); break;
    case Mood::SMOKE:  drawBarEyes(4, 11); drawCigarette(); break;
    case Mood::COOK:   drawBarEyes(6, 15); drawChefHat(); drawPan(); break;
  }
}

void setMood(Mood m) {
  mood = m;
  blinking = false;
  dizzySpin = 0;
  tft.fillScreen(CRAB);
  drawMoodBase();
  blinkAt = millis() + 2200 + (uint32_t)random(0, 1800);
  animAt = millis();
}

void enterIdle() {
  mode = Mode::IDLE;
  setMood(mood);  // redraw the current mood as the idle face
}

void animateMood() {
  const uint32_t now = millis();
  switch (mood) {
    case Mood::AWAKE:
      if (!blinking && now >= blinkAt) {
        blinking = true; blinkUntil = now + 180;
        wipeFace(); eyeSquint(EYE_LX, false); eyeSquint(EYE_RX, true);
      } else if (blinking && now >= blinkUntil) {
        blinking = false; wipeFace(); eyeSquare(EYE_LX); eyeSquare(EYE_RX);
        blinkAt = now + 2200 + (uint32_t)random(0, 2600);
      }
      break;
    case Mood::SLEEPY:
      if (!blinking && now >= blinkAt) {
        blinking = true; blinkUntil = now + 260;
        wipeFace(); eyeFlat(EYE_LX); eyeFlat(EYE_RX);
      } else if (blinking && now >= blinkUntil) {
        blinking = false; wipeFace(); eyeSleepy(EYE_LX); eyeSleepy(EYE_RX);
        blinkAt = now + 3500 + (uint32_t)random(0, 3000);
      }
      break;
    case Mood::DIZZY:
      if (now - animAt > 110) {
        animAt = now; dizzySpin += 0.4f;
        wipeFace(); eyeSpiral(EYE_LX, dizzySpin); eyeSpiral(EYE_RX, -dizzySpin);
      }
      break;
    case Mood::SMOKE:
      if (now - animAt > 150) {
        animAt = now;
        smokePhase = (smokePhase + 3) % 32;
        tft.fillRect(110, 62, 16, 40, CRAB);  // wipe the smoke column
        drawSmoke(114, 96, smokePhase);
      }
      break;
    case Mood::COOK:
      if (now - animAt > 150) {
        animAt = now;
        smokePhase = (smokePhase + 3) % 32;
        tft.fillRect(110, 66, 16, 38, CRAB);  // wipe the steam column
        drawSmoke(114, 100, smokePhase);
      }
      break;
    default:
      break;  // FOCUS and ALERT are static
  }
}

Mood parseMood(const String& s) {
  if (s == "SLEEPY") return Mood::SLEEPY;
  if (s == "FOCUS") return Mood::FOCUS;
  if (s == "DIZZY") return Mood::DIZZY;
  if (s == "SMOKE") return Mood::SMOKE;
  if (s == "COOK") return Mood::COOK;
  return Mood::AWAKE;
}

// Local preview: step through the moods (bound to the middle button).
void cycleMood() {
  int n = (int)mood + 1;
  if (n > (int)Mood::COOK) n = 0;
  setMood((Mood)n);
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

  // little coral claws flanking the header — claws-up on a prompt
  for (int s = 0; s < 2; s++) {
    int x = s == 0 ? 3 : SCREEN_W - 9;
    tft.drawLine(x, 16, x + 2, 25, CRAB);
    tft.drawLine(x + 6, 16, x + 4, 25, CRAB);
  }

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

// ================= usage screen (left button when idle) =================
// Shows the real plan-limit bars from the bridge's PLAN command -- the actual
// `claude` /usage session and week percentages, not an estimate.

void drawPlanBar(int y, const char* label, int pct) {
  tft.setTextSize(1);
  tft.setTextColor(DIM);
  tft.setCursor(6, y);
  tft.print(label);

  tft.setTextColor(ST77XX_WHITE);
  tft.setCursor(SCREEN_W - 30, y);
  if (pct < 0) {
    tft.print("--");
  } else {
    tft.print(pct);
    tft.print("%");
  }

  const int bx = 6, by = y + 12, bw = SCREEN_W - 12, bh = 14;
  tft.drawRect(bx, by, bw, bh, ST77XX_WHITE);
  if (pct >= 0) {
    int clamped = pct > 100 ? 100 : pct;
    int fill = (bw - 2) * clamped / 100;
    uint16_t c = clamped >= 90 ? ST77XX_RED : (clamped >= 70 ? ST77XX_YELLOW : ST77XX_GREEN);
    if (fill > 0) tft.fillRect(bx + 1, by + 1, fill, bh - 2, c);
  }
}

void drawUsage() {
  mode = Mode::USAGE;
  tft.fillScreen(ST77XX_BLACK);
  tft.setTextSize(1);
  tft.setTextColor(CRAB);
  tft.setCursor(6, 4);
  tft.print("PLAN USAGE");

  drawPlanBar(20, "SESSION", planSessionPct);
  drawPlanBar(64, "WEEK", planWeekPct);

  tft.setTextSize(1);
  tft.setTextColor(DIM);
  tft.setCursor(6, 112);
  tft.print(planSessionPct < 0 ? "waiting for data" : "any button: back");
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
  } else if (line.startsWith("MOOD ")) {
    Mood m = parseMood(line.substring(5));
    mood = m;                        // remember it even during a prompt
    if (mode == Mode::IDLE) setMood(m);
  } else if (line.startsWith("USAGE ")) {
    int s1 = line.indexOf(' ', 6);
    int s2 = line.indexOf(' ', s1 + 1);
    if (s1 > 0 && s2 > 0) {
      usageCost = line.substring(6, s1).toFloat();
      usageTokens = line.substring(s1 + 1, s2).toInt();
      usagePct = line.substring(s2 + 1).toInt();
      if (mode == Mode::USAGE) drawUsage();  // live-refresh if being viewed
    }
  } else if (line.startsWith("PLAN ")) {
    int s1 = line.indexOf(' ', 5);
    if (s1 > 0) {
      planSessionPct = line.substring(5, s1).toInt();
      planWeekPct = line.substring(s1 + 1).toInt();
      if (mode == Mode::USAGE) drawUsage();  // live-refresh if being viewed
    }
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

// ================= link: WiFi/WebSocket ("away") or BLE ("home") =================
// Each variant provides setupLink(), loopLink(), and sendButtonLink(name).

#ifdef KEYTAG_WIFI

WebSocketsClient webSocket;
bool wsConnected = false;

void onWsEvent(WStype_t type, uint8_t* payload, size_t length) {
  if (type == WStype_CONNECTED) {
    wsConnected = true;
    Serial.println("[ws] connected to bridge");
  } else if (type == WStype_DISCONNECTED) {
    wsConnected = false;
    Serial.println("[ws] disconnected");
  } else if (type == WStype_TEXT) {
    for (size_t i = 0; i < length; i++) feedByte((char)payload[i]);
  }
}

void setupLink() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);  // non-blocking; the WS client retries once WiFi is up
  Serial.print("[wifi] joining ");
  Serial.println(WIFI_SSID);
  String path = String("/keytag?token=") + KEYTAG_TOKEN;
#if defined(BRIDGE_TLS) && BRIDGE_TLS
#ifdef BRIDGE_HAS_CA
  webSocket.beginSslWithCA(BRIDGE_HOST, BRIDGE_PORT, path.c_str(), BRIDGE_CA_CERT);  // validated wss
#else
  webSocket.beginSSL(BRIDGE_HOST, BRIDGE_PORT, path.c_str());  // wss, cert NOT validated (set BRIDGE_CA_CERT)
#endif
#else
  webSocket.begin(BRIDGE_HOST, BRIDGE_PORT, path.c_str());  // plain ws:// (LAN)
#endif
  webSocket.onEvent(onWsEvent);
  webSocket.setReconnectInterval(3000);
}

void loopLink() {
  // One-shot WiFi log + periodic status while not up. Status codes:
  // 1=NO_SSID (name wrong / 5GHz), 4=CONNECT_FAILED (bad password), 3=CONNECTED.
  static bool wifiUp = false;
  static uint32_t lastLog = 0;
  wl_status_t st = WiFi.status();
  if (!wifiUp && st == WL_CONNECTED) {
    wifiUp = true;
    Serial.print("[wifi] connected, IP ");
    Serial.println(WiFi.localIP());
    configTime(0, 0, "pool.ntp.org", "time.google.com");  // real time for TLS cert validity
  } else if (!wifiUp && millis() - lastLog > 3000) {
    lastLog = millis();
    Serial.print("[wifi] status ");
    Serial.println((int)st);
  }
  webSocket.loop();
}

void sendButtonLink(const char* name) {
  if (wsConnected) {
    String msg = String("BTN ") + name + "\n";
    webSocket.sendTXT(msg);
  }
}

#else  // BLE (Nordic UART Service)

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

void setupLink() {
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

void loopLink() {}

void sendButtonLink(const char* name) {
  if (txChar != nullptr && bleConnected) {
    String msg = String("BTN ") + name + "\n";
    txChar->setValue((uint8_t*)msg.c_str(), msg.length());
    txChar->notify();
  }
}

#endif

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
  sendButtonLink(name);  // BLE notify or WebSocket send, per build
}

void pollButtons() {
  uint32_t now = millis();
  for (Button& b : buttons) {
    bool pressed = digitalRead(b.pin) == LOW;
    if (pressed && !b.wasPressed && (now - b.lastEdge) > 40) {
      b.lastEdge = now;
      if (mode == Mode::USAGE) {
        enterIdle();  // any button leaves the usage screen
      } else if (mode == Mode::IDLE && b.pin == PIN_AUX) {
        cycleMood();  // middle previews moods locally
      } else if (mode == Mode::IDLE && b.pin == PIN_DENY) {
        drawUsage();  // left shows the usage meter
      } else {
        sendButton(b.name);  // prompt decisions and everything else
      }
    }
    b.wasPressed = pressed;
  }
}

// Onboard LED = link status: solid when fully online, slow blink when the WiFi
// is up but not yet talking to the bridge, fast blink when disconnected.
void updateLed() {
#if LED_PIN >= 0
  static uint32_t last = 0;
  static bool on = false;
#ifdef KEYTAG_WIFI
  bool wifiUp = (WiFi.status() == WL_CONNECTED);
  uint32_t interval = (wifiUp && wsConnected) ? 0 : (wifiUp ? 700 : 150);
#else
  uint32_t interval = bleConnected ? 0 : 150;
#endif
  uint32_t now = millis();
  if (interval == 0) {
    on = true;
  } else if (now - last >= interval) {
    last = now;
    on = !on;
  }
  digitalWrite(LED_PIN, on ? LOW : HIGH);  // active low: LOW = lit
#endif
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_DENY, INPUT_PULLUP);
  pinMode(PIN_AUX, INPUT_PULLUP);
  pinMode(PIN_ALLOW, INPUT_PULLUP);
#if LED_PIN >= 0
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);  // off (active low)
#endif

  randomSeed(micros());

  tft.initR(INITR_BLACKTAB);  // 1.8" 128x160; if colors/edges look off, try INITR_GREENTAB
  tft.setRotation(1);         // landscape 160x128 (try 3 to flip 180°)
  CRAB = tft.color565(205, 92, 70);  // Claude coral (green pulled down; ST7735 renders green hot)
  DENY_COL = tft.color565(198, 58, 52);
  ALLOW_COL = tft.color565(58, 158, 92);
  DIM = tft.color565(150, 150, 150);

  setupLink();
  enterIdle();
  Serial.println("READY");
}

void loop() {
  loopLink();
  updateLed();
  pollSerial();
  pollButtons();
  if (mode == Mode::IDLE) {
    animateMood();
  }
}
