// Deck 5x2 - Firmware v0.3
// ---------------------------------------------------------------------------
// Das Deck spricht ueber das USB-Kabel mit der Deck-App (Windows).
//  - Laeuft die App: Sie zeichnet Tasten und Leiste als Bilder (Icons, Umlaute, Wetter, GIFs ...)
//    und schickt sie ans Deck. Tastendruecke, Tippen und Wischen auf der Leiste gehen an die App.
//  - Laeuft keine App: Das Deck zeichnet selbst (Beschriftung + Farbe aus der App, Uhr)
//    und die Tasten senden F13 bis F22 wie eine normale Tastatur.
//
// Arduino IDE, Tools:
//   Board "ESP32S3 Dev Module", USB Mode "USB-OTG (TinyUSB)", USB CDC On Boot "Enabled",
//   Flash Size 16MB, PSRAM "OPI PSRAM", Partition "16M Flash (3MB APP/9.9MB FATFS)"
// Bibliotheken: LovyanGFX, ArduinoJson (beide im Bibliotheksverwalter)
//
// Protokoll: eine JSON-Zeile pro Nachricht, Bilder folgen direkt als Bytes. Siehe docs/protokoll.md
// ---------------------------------------------------------------------------

#define FW_VERSION "0.3.1"

// Optional: WLAN fuer die Uhr, wenn die App nicht laeuft (leer lassen = aus)
const char* WLAN_NAME     = "";
const char* WLAN_PASSWORT = "";

// Optional: Helligkeit. Dafuer LED vom Display nicht an 3V3, sondern ueber einen
// Transistor an diesen Pin legen (z. B. 8). -1 = Helligkeit nicht einstellbar.
#define PIN_LICHT -1

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
LGFX_Sprite bildspeicher(&lcd);      // ganzes Bild 480x320 im PSRAM, so wie die App es geschickt hat
Preferences prefs;
USBHIDKeyboard Tastatur;
USBHIDConsumerControl Medien;

uint16_t cal[8] = {0, 0, 0, 0, 0, 0, 0, 0};
bool calOk = false;

// ---------------------------------------------------------------- Layout
// Pixel-Layout passend zum Gehaeuse (5,75 px pro mm, Tastenabstand 16,7 mm)
const int B = 480, H = 320;
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

// Layout als JSON: {"keys":[{"text":"Spotify","color":"#1DB954"}, ...]} (fuer den Betrieb ohne App)
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

// ---------------------------------------------------------------- Zustand
bool appVerbunden = false;   // App schickt Herzschlaege
bool appBild = false;        // App zeichnet den Bildschirm (sonst zeichnet das Deck selbst)
bool testModus = false;      // Touch-Test: Beruehrungen gehen als Koordinaten an die App
bool schlaeft = false;       // Bildschirmschoner aktiv
uint32_t schlafNachMs = 0;   // 0 = nie
uint32_t letzteBeruehrung = 0;
bool zeitGesetzt = false;
int letzteMinute = -1;
bool leisteZeigtApp = false;

// ---------------------------------------------------------------- Zeichnen ohne App
void zeichneTasteSelbst(int i, bool gedrueckt) {
  int x = KX[i % 5] - KEY / 2, y = KY[i / 5] - KEY / 2;
  lcd.fillRect(x, y, KEY, KEY, TFT_BLACK);
  lcd.fillRoundRect(x, y, KEY, KEY, 12, gedrueckt ? TFT_WHITE : tasten[i].farbe);
  lcd.setTextColor(gedrueckt ? TFT_BLACK : TFT_WHITE);
  lcd.setTextDatum(textdatum_t::middle_center);
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

const char* WOCHENTAG[7] = {"Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"};

void zeichneLeisteSelbst(bool erzwingen) {
  struct tm t;
  bool zeitDa = zeitGesetzt && getLocalTime(&t, 5);
  if (!erzwingen && zeitDa && t.tm_min == letzteMinute && leisteZeigtApp == appVerbunden) return;
  static int textZustand = -1;
  if (!erzwingen && !zeitDa && textZustand == 1 && leisteZeigtApp == appVerbunden) return;
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
  lcd.fillCircle(BAR_X + BAR_W - 10, BAR_Y + BAR_H - 10, 3, appVerbunden ? TFT_GREEN : rgb(71, 85, 105));
}

// Bereich aus dem Bildspeicher neu auf das Display bringen
void bereichZeigen(int x, int y, int w, int h) {
  lcd.setClipRect(x, y, w, h);
  bildspeicher.pushSprite(0, 0);
  lcd.clearClipRect();
}

void zeichneAlles() {
  if (appBild) { bereichZeigen(0, 0, B, H); return; }
  lcd.fillScreen(TFT_BLACK);
  for (int i = 0; i < 10; i++) zeichneTasteSelbst(i, false);
  zeichneLeisteSelbst(true);
}

void zeichneTaste(int i, bool gedrueckt) {
  if (!appBild) { zeichneTasteSelbst(i, gedrueckt); return; }
  int x = KX[i % 5] - KEY / 2, y = KY[i / 5] - KEY / 2;
  bereichZeigen(x, y, KEY, KEY);
  if (gedrueckt) {                       // weisser Rahmen als Rueckmeldung
    for (int r = 0; r < 3; r++) lcd.drawRoundRect(x + r, y + r, KEY - 2 * r, KEY - 2 * r, 12 - r, TFT_WHITE);
  }
}

// ---------------------------------------------------------------- Helligkeit / Schlafen
uint8_t helligkeit = 100;
void lichtSetzen(uint8_t prozent) {
#if PIN_LICHT >= 0
  ledcWrite(PIN_LICHT, (uint32_t)prozent * 255 / 100);
#endif
}

void schlafen() {
  if (schlaeft) return;
  schlaeft = true;
  lcd.fillScreen(TFT_BLACK);
  lichtSetzen(0);
}

void aufwachen();   // weiter unten (braucht sende)

// ---------------------------------------------------------------- Bilder dekodieren
// Pixel kommen als RGB565, hoeherwertiges Byte zuerst. Mit z=1 komprimiert:
//   Steuerbyte c < 128: c+1 Pixel folgen unveraendert
//   Steuerbyte c >= 128: das naechste Pixel (c-126)-mal wiederholen
bool dekodiere(const uint8_t* q, size_t n, uint8_t* ziel, size_t pixel, bool rle) {
  size_t bytes = pixel * 2;
  if (!rle) { if (n != bytes) return false; memcpy(ziel, q, n); return true; }
  size_t i = 0, o = 0;
  while (i < n && o < bytes) {
    uint8_t c = q[i++];
    if (c < 128) {
      size_t len = (size_t)(c + 1) * 2;
      if (i + len > n || o + len > bytes) return false;
      memcpy(ziel + o, q + i, len); i += len; o += len;
    } else {
      size_t anz = c - 126;
      if (i + 2 > n || o + anz * 2 > bytes) return false;
      uint8_t a = q[i], b = q[i + 1]; i += 2;
      for (size_t k = 0; k < anz; k++) { ziel[o++] = a; ziel[o++] = b; }
    }
  }
  return o == bytes;
}

void inBildspeicher(int x, int y, int w, int h, const uint8_t* px) {
  uint8_t* fb = (uint8_t*)bildspeicher.getBuffer();
  for (int r = 0; r < h; r++) memcpy(fb + ((size_t)(y + r) * B + x) * 2, px + (size_t)r * w * 2, (size_t)w * 2);
}

// ---------------------------------------------------------------- Animationen (GIFs)
struct Anim { bool aktiv; int x, y, w, h, n, cur; uint8_t* daten; uint16_t* ms; uint32_t naechste; };
const int ANIM_PLAETZE = 4;
Anim anims[ANIM_PLAETZE];

void animStoppen(int s) {
  if (s < 0 || s >= ANIM_PLAETZE) return;
  if (anims[s].daten) free(anims[s].daten);
  if (anims[s].ms) free(anims[s].ms);
  anims[s] = Anim{};
}

void animsZeichnen() {
  if (!appBild || schlaeft || testModus) return;
  uint32_t jetzt = millis();
  for (int s = 0; s < ANIM_PLAETZE; s++) {
    Anim& a = anims[s];
    if (!a.aktiv || (int32_t)(jetzt - a.naechste) < 0) continue;
    const uint8_t* bild = a.daten + (size_t)a.cur * a.w * a.h * 2;
    lcd.pushImage(a.x, a.y, a.w, a.h, (const lgfx::swap565_t*)bild);
    inBildspeicher(a.x, a.y, a.w, a.h, bild);
    a.naechste = jetzt + max<uint16_t>(a.ms[a.cur], 20);
    a.cur = (a.cur + 1) % a.n;
  }
}

// ---------------------------------------------------------------- Kommunikation
void sende(JsonDocument& doc) {
  serializeJson(doc, Serial);
  Serial.print('\n');
}

void sendeHallo() {
  JsonDocument d;
  d["t"] = "hello"; d["fw"] = FW_VERSION; d["device"] = "Deck 5x2";
  d["keys"] = 10; d["cal"] = calOk; d["w"] = B; d["h"] = H;
  d["psram"] = ESP.getFreePsram();
  d["light"] = PIN_LICHT >= 0;
  JsonArray c = d["caps"].to<JsonArray>();
  c.add("img"); c.add("anim"); c.add("rle"); c.add("touch"); c.add("sleep");
  sende(d);
}

void sendeKalibrierung() {
  JsonDocument d;
  d["t"] = "cal";
  JsonArray a = d["v"].to<JsonArray>();
  for (int i = 0; i < 8; i++) a.add(cal[i]);
  sende(d);
}

void aufwachen() {
  if (!schlaeft) return;
  schlaeft = false;
  lichtSetzen(helligkeit);
  zeichneAlles();
  if (appVerbunden) { JsonDocument d; d["t"] = "wake"; sende(d); }
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

void touchTestZeichnen() {
  lcd.fillScreen(TFT_BLACK);
  for (int i = 0; i < 10; i++)
    lcd.drawRoundRect(KX[i % 5] - KEY / 2, KY[i / 5] - KEY / 2, KEY, KEY, 12, rgb(71, 85, 105));
  lcd.drawRoundRect(BAR_X, BAR_Y, BAR_W, BAR_H, 10, rgb(71, 85, 105));
  lcd.setFont(&fonts::FreeSans9pt7b);
  lcd.setTextDatum(textdatum_t::middle_center);
  lcd.setTextColor(GRAU);
  lcd.drawString("Touch-Test: zeichne mit dem Stift", BAR_X + BAR_W / 2, BAR_Y + BAR_H / 2);
}

// Empfang: entweder eine JSON-Zeile oder (nach img/anim) eine feste Anzahl Bytes
uint32_t letzterHerzschlag = 0, letzteBytes = 0;
String eingang;
struct Empfang { bool aktiv; char typ; int x, y, w, h, slot, frames; bool rle; size_t len, pos; uint8_t* buf; uint16_t* ms; };
Empfang rx = {};

void empfangAbbrechen() {
  if (rx.buf) free(rx.buf);
  if (rx.ms) free(rx.ms);
  rx = Empfang{};
}

void bytesFertig() {
  size_t pixel = (size_t)rx.w * rx.h;
  bool ok = false;
  if (rx.typ == 'i') {
    uint8_t* px = (uint8_t*)heap_caps_malloc(pixel * 2, MALLOC_CAP_SPIRAM);
    if (px && dekodiere(rx.buf, rx.len, px, pixel, rx.rle)) {
      inBildspeicher(rx.x, rx.y, rx.w, rx.h, px);
      if (appBild && !schlaeft && !testModus) lcd.pushImage(rx.x, rx.y, rx.w, rx.h, (const lgfx::swap565_t*)px);
      ok = true;
    }
    if (px) free(px);
  } else if (rx.typ == 'a') {
    animStoppen(rx.slot);
    uint8_t* px = (uint8_t*)heap_caps_malloc(pixel * 2 * rx.frames, MALLOC_CAP_SPIRAM);
    if (px && dekodiere(rx.buf, rx.len, px, pixel * rx.frames, rx.rle)) {
      Anim& a = anims[rx.slot];
      a.aktiv = true; a.x = rx.x; a.y = rx.y; a.w = rx.w; a.h = rx.h; a.n = rx.frames; a.cur = 0;
      a.daten = px; a.ms = rx.ms; rx.ms = nullptr; a.naechste = millis();
      ok = true;
    } else if (px) free(px);
  }
  JsonDocument d; d["t"] = "ok"; d["for"] = rx.typ == 'i' ? "img" : "anim"; d["ok"] = ok;
  sende(d);
  empfangAbbrechen();
}

// Kopf fuer Bilddaten pruefen und Empfang vorbereiten
void bytesErwarten(JsonDocument& doc, char typ) {
  empfangAbbrechen();
  int x = doc["x"] | 0, y = doc["y"] | 0, w = doc["w"] | 0, h = doc["h"] | 0;
  size_t n = doc["n"] | 0;
  int frames = typ == 'a' ? (doc["frames"] | 1) : 1;
  int slot = doc["slot"] | 0;
  bool gueltig = w > 0 && h > 0 && x >= 0 && y >= 0 && x + w <= B && y + h <= H && n > 0
                 && n <= 6 * 1024 * 1024 && frames >= 1 && frames <= 600 && slot >= 0 && slot < ANIM_PLAETZE;
  rx.aktiv = true; rx.typ = typ; rx.len = n; rx.pos = 0;
  rx.x = x; rx.y = y; rx.w = w; rx.h = h; rx.frames = frames; rx.slot = slot; rx.rle = (doc["z"] | 0) == 1;
  rx.buf = gueltig ? (uint8_t*)heap_caps_malloc(n, MALLOC_CAP_SPIRAM) : nullptr;
  if (typ == 'a' && rx.buf) {
    rx.ms = (uint16_t*)malloc(sizeof(uint16_t) * frames);
    JsonVariantConst ms = doc["ms"];
    for (int i = 0; i < frames; i++)
      rx.ms[i] = ms.is<JsonArrayConst>() ? (ms[i] | 100) : (ms | 100);
  }
  // Ist etwas ungueltig, werden die Bytes trotzdem gelesen und verworfen (rx.buf == nullptr)
}

void nachrichtVerarbeiten(const String& zeile) {
  JsonDocument doc;
  if (deserializeJson(doc, zeile)) return;              // keine gueltige Nachricht
  const char* t = doc["t"] | "";
  letzterHerzschlag = millis();
  if (!appVerbunden) { appVerbunden = true; if (!appBild && !schlaeft && !testModus) zeichneLeisteSelbst(true); }

  if (!strcmp(t, "hb")) {
    // nur Herzschlag
  } else if (!strcmp(t, "hello?")) {
    sendeHallo();
  } else if (!strcmp(t, "time")) {
    struct timeval tv = { (time_t)(doc["local"] | 0LL), 0 };
    setenv("TZ", "UTC0", 1); tzset();
    settimeofday(&tv, nullptr);
    zeitGesetzt = true;
    letzteMinute = -1;
    if (!appBild && !schlaeft && !testModus) zeichneLeisteSelbst(true);
  } else if (!strcmp(t, "layout")) {
    if (layoutAnwenden(doc.as<JsonVariantConst>())) {
      prefs.putString("layout", zeile);
      if (!appBild && !schlaeft && !testModus) for (int i = 0; i < 10; i++) zeichneTasteSelbst(i, false);
      JsonDocument a; a["t"] = "ok"; a["for"] = "layout"; sende(a);
    }
  } else if (!strcmp(t, "screen")) {
    // {"t":"screen","app":true}: ab jetzt zeigt das Deck die Bilder der App
    bool neu = doc["app"] | false;
    if (neu && !appBild) { bildspeicher.fillScreen(TFT_BLACK); }
    appBild = neu;
    if (!neu) for (int s = 0; s < ANIM_PLAETZE; s++) animStoppen(s);
    if (!schlaeft && !testModus) zeichneAlles();
  } else if (!strcmp(t, "img")) {
    bytesErwarten(doc, 'i');
    letzteBytes = millis();
  } else if (!strcmp(t, "anim")) {
    if (doc["stop"] | false) animStoppen(doc["slot"] | 0);
    else { bytesErwarten(doc, 'a'); letzteBytes = millis(); }
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
      sendeKalibrierung();
    }
  } else if (!strcmp(t, "touchtest")) {
    bool an = doc["on"] | false;
    if (an && !testModus) { aufwachen(); testModus = true; touchTestZeichnen(); }
    else if (!an && testModus) { testModus = false; zeichneAlles(); }
  } else if (!strcmp(t, "sleep")) {
    if (doc["on"] | false) schlafen(); else aufwachen();
  } else if (!strcmp(t, "cfg")) {
    if (doc["sleep_s"].is<int>()) { schlafNachMs = (uint32_t)(doc["sleep_s"] | 0) * 1000; prefs.putUInt("sleep_s", schlafNachMs / 1000); }
    if (doc["bright"].is<int>()) {
      helligkeit = constrain(doc["bright"] | 100, 5, 100);
      prefs.putUChar("bright", helligkeit);
      if (!schlaeft) lichtSetzen(helligkeit);
    }
    letzteBeruehrung = millis();
  }
}

void eingangLesen() {
  static uint8_t puffer[4096];
  while (Serial.available()) {
    if (rx.aktiv) {
      size_t n = min((size_t)Serial.available(), min(sizeof(puffer), rx.len - rx.pos));
      n = Serial.read(puffer, n);
      if (rx.buf) memcpy(rx.buf + rx.pos, puffer, n);
      rx.pos += n;
      letzterHerzschlag = letzteBytes = millis();
      if (rx.pos >= rx.len) {
        if (rx.buf) bytesFertig(); else { JsonDocument d; d["t"] = "ok"; d["for"] = "img"; d["ok"] = false; sende(d); empfangAbbrechen(); }
      }
      continue;
    }
    char c = Serial.read();
    if (c == '\n') { String z = eingang; eingang = ""; if (z.length()) nachrichtVerarbeiten(z); }
    else if (c != '\r' && eingang.length() < 8192) eingang += c;
  }
  // Bilddaten unvollstaendig (Bytes verloren)? Nach 1 s abbrechen und der App Bescheid geben
  if (rx.aktiv && millis() - letzteBytes > 1000) {
    empfangAbbrechen();
    JsonDocument d; d["t"] = "ok"; d["for"] = "img"; d["ok"] = false; d["lost"] = true; sende(d);
  }
  // Ohne Herzschlag fuer 6 Sekunden gilt die App als beendet -> Deck zeichnet wieder selbst
  if (appVerbunden && millis() - letzterHerzschlag > 6000) {
    appVerbunden = false;
    if (rx.aktiv) empfangAbbrechen();
    if (appBild) { appBild = false; for (int s = 0; s < ANIM_PLAETZE; s++) animStoppen(s); }
    if (testModus) testModus = false;
    if (!schlaeft) zeichneAlles();
  }
}

// ---------------------------------------------------------------- Tasten und Leiste
int tasteBei(int x, int y) {
  for (int i = 0; i < 10; i++)
    if (abs(x - KX[i % 5]) <= KEY / 2 + 4 && abs(y - KY[i / 5]) <= KEY / 2 + 4) return i;
  return -1;
}

bool aufLeiste(int x, int y) { return y >= BAR_Y - 4 && x >= BAR_X - 4 && x <= BAR_X + BAR_W + 4; }

void tasteMelden(int i, bool unten) {
  if (appVerbunden) {
    JsonDocument d; d["t"] = "key"; d["i"] = i; d["down"] = unten;
    sende(d);
  } else {
    if (unten) Tastatur.press(F_TASTEN[i]); else Tastatur.release(F_TASTEN[i]);
  }
}

// ---------------------------------------------------------------- Start
void setup() {
  Serial.setRxBufferSize(32768);
  Tastatur.begin();
  Medien.begin();
  USB.productName("Deck 5x2");
  USB.manufacturerName("Deck 5x2");
  USB.begin();
  Serial.begin(115200);

#if PIN_LICHT >= 0
  ledcAttach(PIN_LICHT, 5000, 8);
#endif

  lcd.init();
  lcd.setRotation(1);
  prefs.begin("deck", false);
  helligkeit = prefs.getUChar("bright", 100);
  schlafNachMs = prefs.getUInt("sleep_s", 0) * 1000;
  lichtSetzen(helligkeit);

  bildspeicher.setColorDepth(16);
  bildspeicher.setPsram(true);
  bildspeicher.createSprite(B, H);
  bildspeicher.fillScreen(TFT_BLACK);

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
    zeitGesetzt = true;
  }

  zeichneAlles();
  letzteBeruehrung = millis();
  sendeHallo();
}

int aktiv = -1;                 // gedrueckte Taste
bool leisteUnten = false;       // Stift auf der Leiste
int leisteStartX = 0, leisteStartY = 0, leisteLetztX = 0;
bool weckBeruehrung = false;    // Beruehrung, die nur aufgeweckt hat, wird ignoriert
uint32_t letzteAenderung = 0, letzteUhr = 0, letzterTestPunkt = 0;

void loop() {
  eingangLesen();
  if (rx.aktiv) return;                                // Bilddaten zuerst fertig lesen

  int32_t x, y;
  bool beruehrt = lcd.getTouch(&x, &y);
  uint32_t jetzt = millis();
  if (beruehrt) letzteBeruehrung = jetzt;

  if (schlaeft) {
    if (beruehrt) { weckBeruehrung = true; aufwachen(); }
    delay(10);
    return;
  }
  if (weckBeruehrung) { if (!beruehrt) weckBeruehrung = false; delay(5); return; }

  if (testModus) {
    static bool warUnten = false;
    if (beruehrt && jetzt - letzterTestPunkt > 25) {
      lcd.fillCircle(x, y, 3, rgb(60, 196, 211));
      JsonDocument d; d["t"] = "touch"; d["x"] = x; d["y"] = y; sende(d);
      letzterTestPunkt = jetzt; warUnten = true;
    } else if (!beruehrt && warUnten) {
      JsonDocument d; d["t"] = "touch"; d["up"] = true; sende(d);
      warUnten = false;
    }
    delay(4);
    return;
  }

  // Leiste: Tippen und Wischen (nur mit App)
  if (beruehrt && appVerbunden && aktiv < 0 && (leisteUnten || aufLeiste(x, y))) {
    if (!leisteUnten) { leisteUnten = true; leisteStartX = x; leisteStartY = y; }
    leisteLetztX = x;
  } else if (!beruehrt && leisteUnten) {
    leisteUnten = false;
    int dx = leisteLetztX - leisteStartX;
    JsonDocument d;
    if (abs(dx) > 70) { d["t"] = "swipe"; d["dir"] = dx < 0 ? "left" : "right"; }
    else { d["t"] = "tap"; d["x"] = leisteStartX; d["y"] = leisteStartY; }
    sende(d);
  }

  if (!leisteUnten) {
    int k = beruehrt ? tasteBei(x, y) : -1;
    if (k != aktiv && jetzt - letzteAenderung > 30) {
      if (aktiv >= 0) { tasteMelden(aktiv, false); zeichneTaste(aktiv, false); }
      if (k >= 0)     { tasteMelden(k, true);      zeichneTaste(k, true); }
      aktiv = k;
      letzteAenderung = jetzt;
    }
  }

  animsZeichnen();
  if (!appBild && jetzt - letzteUhr > 1000) { zeichneLeisteSelbst(false); letzteUhr = jetzt; }
  if (schlafNachMs && aktiv < 0 && !leisteUnten && jetzt - letzteBeruehrung > schlafNachMs) schlafen();
  delay(4);
}
