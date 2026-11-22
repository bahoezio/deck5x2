// Deck 5x2 - Firmware v0.2
// ---------------------------------------------------------------------------
// Neu in v0.2: Das Deck spricht ueber das USB-Kabel mit der Deck-App (Windows).
//  - Laeuft die App: Tastendruecke gehen an die App, die App fuehrt die Aktion aus
//    (Programm starten, Webseite, Tastenkuerzel ...). Sie stellt auch die Uhrzeit.
//  - Laeuft keine App: Die Tasten senden F13 bis F22 wie eine normale Tastatur.
//  - Beschriftung und Farben kommen aus der App und bleiben im Deck gespeichert.
//
// Arduino IDE, Tools:
//   Board "ESP32S3 Dev Module", USB Mode "USB-OTG (TinyUSB)", USB CDC On Boot "Enabled",
//   Flash Size 16MB, PSRAM "OPI PSRAM", Partition "16M Flash (3MB APP/9.9MB FATFS)"
// Bibliotheken: LovyanGFX, ArduinoJson (beide im Bibliotheksverwalter)
//
// Protokoll (eine JSON-Zeile pro Nachricht, siehe docs/protokoll.md):
//   Deck -> App: {"t":"hello",...} {"t":"key","i":0,"down":true} {"t":"cal","v":[...]}
//   App -> Deck: {"t":"hb"} {"t":"time","local":1795360000} {"t":"layout","keys":[...]}
//                {"t":"calibrate"} {"t":"hello?"}
// ---------------------------------------------------------------------------

#define FW_VERSION "0.2.0"

// Optional: WLAN fuer die Uhr, wenn die App nicht laeuft (leer lassen = aus)
const char* WLAN_NAME     = "";
const char* WLAN_PASSWORT = "";

#include "USB.h"
#include "USBHIDKeyboard.h"
#include "USBHIDConsumerControl.h"
#include <ArduinoJson.h>
#include <Preferences.h>
#include <WiFi.h>
#include <time.h>
#include <sys/time.h>
#define LGFX_USE_V1
#include <LovyanGFX.hpp>

// ---------------------------------------------------------------- Display + Touch
class LGFX : public lgfx::LGFX_Device {
  lgfx::Panel_ST7796  _panel;
  lgfx::Bus_SPI       _bus;
  lgfx::Touch_XPT2046 _touch;
public:
  LGFX() {
    { auto cfg = _bus.config();
      cfg.spi_host = SPI2_HOST; cfg.spi_mode = 0;
      cfg.freq_write = 27000000; cfg.freq_read = 16000000;
      cfg.spi_3wire = false; cfg.use_lock = true; cfg.dma_channel = SPI_DMA_CH_AUTO;
      cfg.pin_sclk = 12; cfg.pin_mosi = 11; cfg.pin_miso = -1; cfg.pin_dc = 9;
      _bus.config(cfg); _panel.setBus(&_bus); }
    { auto cfg = _panel.config();
      cfg.pin_cs = 10; cfg.pin_rst = 14; cfg.pin_busy = -1;
      cfg.panel_width = 320; cfg.panel_height = 480;
      cfg.offset_x = 0; cfg.offset_y = 0; cfg.offset_rotation = 0;
      cfg.readable = false; cfg.invert = false; cfg.rgb_order = false;
      cfg.dlen_16bit = false; cfg.bus_shared = false;
      _panel.config(cfg); }
    { auto cfg = _touch.config();
      cfg.x_min = 300; cfg.x_max = 3900; cfg.y_min = 300; cfg.y_max = 3900;
      cfg.pin_int = -1; cfg.bus_shared = false; cfg.offset_rotation = 0;
      cfg.spi_host = SPI3_HOST; cfg.freq = 1000000;
      cfg.pin_sclk = 4; cfg.pin_mosi = 6; cfg.pin_miso = 7; cfg.pin_cs = 5;
      _touch.config(cfg); _panel.setTouch(&_touch); }
    setPanel(&_panel);
  }
};

LGFX lcd;
Preferences prefs;
USBHIDKeyboard Tastatur;
USBHIDConsumerControl Medien;

// Standard-Kalibrierung (vom Prototyp). Wird ersetzt, sobald das Geraet selbst kalibriert wurde.
uint16_t cal[8] = {0, 0, 0, 0, 0, 0, 0, 0};
bool calOk = false;

// ---------------------------------------------------------------- Layout
// Pixel-Layout passend zum Gehaeuse (5,75 px pro mm, Tastenabstand 16,7 mm)
const int KEY = 76;
const int KX[5] = {48, 144, 240, 336, 432};
const int KY[2] = {48, 144};
const int BAR_X = 9, BAR_Y = 201, BAR_W = 462, BAR_H = 110;

constexpr uint16_t rgb(uint8_t r, uint8_t g, uint8_t b) {
  return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);
}
const uint16_t BAR_FARBE = rgb(17, 24, 39);
const uint16_t GRAU = rgb(148, 163, 184);

struct Taste { char text[24]; uint16_t farbe; };
Taste tasten[10];
const uint8_t F_TASTEN[10] = {KEY_F13, KEY_F14, KEY_F15, KEY_F16, KEY_F17,
                              KEY_F18, KEY_F19, KEY_F20, KEY_F21, KEY_F22};

void standardLayout() {
  const uint16_t farben[10] = {rgb(59,130,246), rgb(225,29,72), rgb(34,197,94), rgb(245,158,11), rgb(139,92,246),
                               rgb(6,182,212), rgb(249,115,22), rgb(236,72,153), rgb(132,204,22), rgb(234,179,8)};
  for (int i = 0; i < 10; i++) {
    snprintf(tasten[i].text, sizeof(tasten[i].text), "F%d", 13 + i);
    tasten[i].farbe = farben[i];
  }
}

uint16_t hexFarbe(const char* s, uint16_t fallback) {
  if (!s || s[0] != '#' || strlen(s) != 7) return fallback;
  long v = strtol(s + 1, nullptr, 16);
  return rgb((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF);
}

// Layout als JSON: {"keys":[{"text":"Spotify","color":"#1DB954"}, ...]}
bool layoutAnwenden(JsonVariantConst doc) {
  JsonArrayConst keys = doc["keys"].as<JsonArrayConst>();
  if (keys.isNull()) return false;
  int i = 0;
  for (JsonVariantConst k : keys) {
    if (i >= 10) break;
    const char* t = k["text"] | "";
    strlcpy(tasten[i].text, t, sizeof(tasten[i].text));
    tasten[i].farbe = hexFarbe(k["color"] | "", tasten[i].farbe);
    i++;
  }
  return true;
}

// ---------------------------------------------------------------- Zeichnen
void zeichneTaste(int i, bool gedrueckt) {
  int x = KX[i % 5] - KEY / 2, y = KY[i / 5] - KEY / 2;
  lcd.fillRoundRect(x, y, KEY, KEY, 12, gedrueckt ? TFT_WHITE : tasten[i].farbe);
  lcd.setTextColor(gedrueckt ? TFT_BLACK : TFT_WHITE);
  lcd.setTextDatum(textdatum_t::middle_center);
  // Langen Text automatisch kleiner setzen bzw. auf zwei Zeilen umbrechen
  const char* t = tasten[i].text;
  lcd.setFont(&fonts::FreeSansBold9pt7b);
  if (lcd.textWidth(t) <= KEY - 8) { lcd.drawString(t, KX[i % 5], KY[i / 5]); return; }
  const char* sp = strchr(t, ' ');
  if (sp) {
    char a[24]; strlcpy(a, t, min((size_t)(sp - t + 1), sizeof(a)));
    lcd.setFont(&fonts::FreeSans9pt7b);
    lcd.drawString(a, KX[i % 5], KY[i / 5] - 10);
    lcd.drawString(sp + 1, KX[i % 5], KY[i / 5] + 10);
  } else {
    lcd.setFont(&fonts::Font2);
    lcd.drawString(t, KX[i % 5], KY[i / 5]);
  }
}

void zeichneAlleTasten() { for (int i = 0; i < 10; i++) zeichneTaste(i, false); }

bool zeitGesetzt = false;
int letzteMinute = -1;
bool appVerbunden = false, leisteZeigtApp = false;
const char* WOCHENTAG[7] = {"Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"};

void zeichneLeiste(bool erzwingen) {
  struct tm t;
  bool zeitDa = zeitGesetzt && getLocalTime(&t, 5);
  if (!erzwingen && zeitDa && t.tm_min == letzteMinute && leisteZeigtApp == appVerbunden) return;
  static int textZustand = -1;
  if (!erzwingen && !zeitDa && textZustand == 1) return;
  textZustand = zeitDa ? 0 : 1;
  leisteZeigtApp = appVerbunden;

  lcd.fillRoundRect(BAR_X, BAR_Y, BAR_W, BAR_H, 10, BAR_FARBE);
  if (zeitDa) {
    char uhr[6], datum[16];
    snprintf(uhr, sizeof(uhr), "%02d:%02d", t.tm_hour, t.tm_min);
    snprintf(datum, sizeof(datum), "%02d.%02d.%04d", t.tm_mday, t.tm_mon + 1, t.tm_year + 1900);
    lcd.setTextColor(TFT_WHITE);
    lcd.setFont(&fonts::FreeSansBold24pt7b);
    lcd.setTextDatum(textdatum_t::middle_left);
    lcd.drawString(uhr, BAR_X + 24, BAR_Y + BAR_H / 2);
    lcd.setFont(&fonts::FreeSans12pt7b);
    lcd.setTextDatum(textdatum_t::middle_right);
    lcd.setTextColor(GRAU);
    lcd.drawString(WOCHENTAG[t.tm_wday], BAR_X + BAR_W - 24, BAR_Y + BAR_H / 2 - 14);
    lcd.drawString(datum, BAR_X + BAR_W - 24, BAR_Y + BAR_H / 2 + 16);
    letzteMinute = t.tm_min;
  } else {
    lcd.setTextColor(TFT_WHITE);
    lcd.setFont(&fonts::FreeSansBold12pt7b);
    lcd.setTextDatum(textdatum_t::middle_center);
    lcd.drawString("Deck 5x2", BAR_X + BAR_W / 2, BAR_Y + BAR_H / 2 - 10);
    lcd.setFont(&fonts::FreeSans9pt7b);
    lcd.setTextColor(GRAU);
    lcd.drawString(strlen(WLAN_NAME) ? "Verbinde mit WLAN ..." : "Deck-App starten fuer die Uhrzeit",
                   BAR_X + BAR_W / 2, BAR_Y + BAR_H / 2 + 16);
  }
  // kleiner Punkt unten rechts: gruen = App verbunden
  lcd.fillCircle(BAR_X + BAR_W - 10, BAR_Y + BAR_H - 10, 3, appVerbunden ? TFT_GREEN : rgb(71, 85, 105));
}

void zeichneAlles() {
  lcd.fillScreen(TFT_BLACK);
  zeichneAlleTasten();
  zeichneLeiste(true);
}

// ---------------------------------------------------------------- Kommunikation
void sende(JsonDocument& doc) {
  serializeJson(doc, Serial);
  Serial.print('\n');
}

void sendeHallo() {
  JsonDocument d;
  d["t"] = "hello"; d["fw"] = FW_VERSION; d["device"] = "Deck 5x2";
  d["keys"] = 10; d["cal"] = calOk;
  sende(d);
}

void sendeKalibrierung() {
  JsonDocument d;
  d["t"] = "cal";
  JsonArray a = d["v"].to<JsonArray>();
  for (int i = 0; i < 8; i++) a.add(cal[i]);
  sende(d);
}

void kalibrieren() {
  lcd.fillScreen(TFT_BLACK);
  lcd.setFont(&fonts::FreeSans12pt7b);
  lcd.setTextDatum(textdatum_t::middle_center);
  lcd.setTextColor(TFT_WHITE);
  lcd.drawString("Tippe genau auf die Pfeilspitzen", lcd.width() / 2, lcd.height() / 2);
  lcd.calibrateTouch(cal, TFT_WHITE, TFT_BLACK, 24);
  prefs.putBytes("cal", cal, sizeof(cal));
  calOk = true;
}

uint32_t letzterHerzschlag = 0;
String eingang;

void nachrichtVerarbeiten(const String& zeile) {
  JsonDocument doc;
  if (deserializeJson(doc, zeile)) return;              // keine gueltige Nachricht
  const char* t = doc["t"] | "";
  letzterHerzschlag = millis();
  if (!appVerbunden) { appVerbunden = true; zeichneLeiste(true); }

  if (!strcmp(t, "hb")) {
    // nur Herzschlag
  } else if (!strcmp(t, "hello?")) {
    sendeHallo();
  } else if (!strcmp(t, "time")) {
    // Die App schickt die lokale Zeit (Sommerzeit schon eingerechnet)
    struct timeval tv = { (time_t)(doc["local"] | 0LL), 0 };
    setenv("TZ", "UTC0", 1); tzset();
    settimeofday(&tv, nullptr);
    zeitGesetzt = true;
    letzteMinute = -1;
    zeichneLeiste(true);
  } else if (!strcmp(t, "layout")) {
    if (layoutAnwenden(doc.as<JsonVariantConst>())) {
      prefs.putString("layout", zeile);
      zeichneAlleTasten();
      JsonDocument a; a["t"] = "ok"; a["for"] = "layout"; sende(a);
    }
  } else if (!strcmp(t, "calibrate")) {
    kalibrieren();
    zeichneAlles();
    sendeKalibrierung();
  } else if (!strcmp(t, "getcal")) {
    sendeKalibrierung();
  } else if (!strcmp(t, "setcal")) {
    JsonArrayConst v = doc["v"].as<JsonArrayConst>();
    if (v.size() == 8) {
      for (int i = 0; i < 8; i++) cal[i] = v[i].as<uint16_t>();
      lcd.setTouchCalibrate(cal);
      prefs.putBytes("cal", cal, sizeof(cal));
      calOk = true;
      JsonDocument a; a["t"] = "ok"; a["for"] = "setcal"; sende(a);
    }
  }
}

void eingangLesen() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { if (eingang.length()) nachrichtVerarbeiten(eingang); eingang = ""; }
    else if (c != '\r' && eingang.length() < 4096) eingang += c;
  }
  // Ohne Herzschlag fuer 6 Sekunden gilt die App als beendet
  if (appVerbunden && millis() - letzterHerzschlag > 6000) { appVerbunden = false; zeichneLeiste(true); }
}

// ---------------------------------------------------------------- Tasten
int tasteBei(int x, int y) {
  for (int i = 0; i < 10; i++)
    if (abs(x - KX[i % 5]) <= KEY / 2 + 4 && abs(y - KY[i / 5]) <= KEY / 2 + 4) return i;
  return -1;
}

void tasteMelden(int i, bool unten) {
  if (appVerbunden) {
    JsonDocument d; d["t"] = "key"; d["i"] = i; d["down"] = unten;
    sende(d);
  } else {
    // Ohne App: wie eine normale Tastatur F13 bis F22 senden
    if (unten) Tastatur.press(F_TASTEN[i]); else Tastatur.release(F_TASTEN[i]);
  }
}

// ---------------------------------------------------------------- Start
void setup() {
  Tastatur.begin();
  Medien.begin();
  USB.productName("Deck 5x2");
  USB.manufacturerName("Deck 5x2");
  USB.begin();
  Serial.begin(115200);

  lcd.init();
  lcd.setRotation(1);
  prefs.begin("deck", false);

  standardLayout();
  String gespeichert = prefs.getString("layout", "");
  if (gespeichert.length()) {
    JsonDocument doc;
    if (!deserializeJson(doc, gespeichert)) layoutAnwenden(doc.as<JsonVariantConst>());
  }

  int32_t tx, ty;
  bool neu = lcd.getTouch(&tx, &ty);                   // Stift beim Start auf dem Display = neu kalibrieren
  if (!neu && prefs.getBytesLength("cal") == sizeof(cal)) {
    prefs.getBytes("cal", cal, sizeof(cal));
    lcd.setTouchCalibrate(cal);
    calOk = true;
  } else {
    kalibrieren();
  }

  if (strlen(WLAN_NAME)) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WLAN_NAME, WLAN_PASSWORT);
    configTzTime("CET-1CEST,M3.5.0,M10.5.0/3", "pool.ntp.org", "time.google.com");
    zeitGesetzt = true;                                // Uhr erscheint, sobald NTP antwortet
  }

  zeichneAlles();
  sendeHallo();
}

int aktiv = -1;
uint32_t letzteAenderung = 0, letzteUhr = 0;

void loop() {
  eingangLesen();

  int32_t x, y;
  int k = lcd.getTouch(&x, &y) ? tasteBei(x, y) : -1;
  if (k != aktiv && millis() - letzteAenderung > 30) {
    if (aktiv >= 0) { tasteMelden(aktiv, false); zeichneTaste(aktiv, false); }
    if (k >= 0)     { tasteMelden(k, true);      zeichneTaste(k, true); }
    aktiv = k;
    letzteAenderung = millis();
  }
  if (millis() - letzteUhr > 1000) { zeichneLeiste(false); letzteUhr = millis(); }
  delay(4);
}
