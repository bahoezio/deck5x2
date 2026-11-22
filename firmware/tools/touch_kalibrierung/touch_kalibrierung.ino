// Deck 5x2 - Touch-Kalibrierung und Tasten-Probelauf
// 1. Nach dem Start erscheinen nacheinander Pfeile in den vier Ecken.
//    Tippe jeweils mit dem Stift genau auf die Pfeilspitze.
// 2. Danach siehst du das geplante Layout: 10 Tasten (5 x 2) und die Leiste.
//    Tippst du eine Taste an, leuchtet sie auf und ihre Nummer steht im Seriellen Monitor.
// 3. Die Kalibrierwerte stehen im Seriellen Monitor (115200 Baud) und werden im ESP32 gespeichert.
//    Neu kalibrieren: beim Einschalten das Display gedrueckt halten.

#define LGFX_USE_V1
#include <LovyanGFX.hpp>

class LGFX : public lgfx::LGFX_Device {
  lgfx::Panel_ST7796  _panel;
  lgfx::Bus_SPI       _bus;
  lgfx::Touch_XPT2046 _touch;

public:
  LGFX() {
    { // Display-Bus (eigene Pins)
      auto cfg = _bus.config();
      cfg.spi_host    = SPI2_HOST;
      cfg.spi_mode    = 0;
      cfg.freq_write  = 27000000;   // fuer Dupont-Kabel; spaeter mit kurzen Kabeln hoeher
      cfg.freq_read   = 16000000;
      cfg.spi_3wire   = false;
      cfg.use_lock    = true;
      cfg.dma_channel = SPI_DMA_CH_AUTO;
      cfg.pin_sclk = 12;   // SCK
      cfg.pin_mosi = 11;   // SDI(MOSI)
      cfg.pin_miso = -1;   // SDO(MISO) bleibt frei
      cfg.pin_dc   = 9;    // DC/RS
      _bus.config(cfg);
      _panel.setBus(&_bus);
    }
    { // Display
      auto cfg = _panel.config();
      cfg.pin_cs   = 10;   // CS
      cfg.pin_rst  = 14;   // RESET
      cfg.pin_busy = -1;
      cfg.panel_width  = 320;
      cfg.panel_height = 480;
      cfg.offset_x = 0;
      cfg.offset_y = 0;
      cfg.offset_rotation = 0;
      cfg.readable   = false;
      cfg.invert     = false;
      cfg.rgb_order  = false;
      cfg.dlen_16bit = false;
      cfg.bus_shared = false;
      _panel.config(cfg);
    }
    { // Touch (eigener Bus, damit sich Display und Touch nicht stoeren)
      auto cfg = _touch.config();
      cfg.x_min = 300;  cfg.x_max = 3900;   // grobe Startwerte, Kalibrierung kommt spaeter
      cfg.y_min = 300;  cfg.y_max = 3900;
      cfg.pin_int = -1;                     // T_IRQ wird nicht benutzt (Touch wird direkt abgefragt)
      cfg.bus_shared = false;
      cfg.offset_rotation = 0;
      cfg.spi_host = SPI3_HOST;
      cfg.freq     = 1000000;
      cfg.pin_sclk = 4;    // T_CLK
      cfg.pin_mosi = 6;    // T_DIN
      cfg.pin_miso = 7;    // T_DO
      cfg.pin_cs   = 5;    // T_CS
      _touch.config(cfg);
      _panel.setTouch(&_touch);
    }
    setPanel(&_panel);
  }
};

LGFX lcd;

#include <Preferences.h>
Preferences prefs;
uint16_t cal[8];

// Geplantes Layout in Pixeln (480 x 320), aus den Gehaeusemassen umgerechnet (5,75 px pro mm)
const int KEY = 76;                                   // Tastenfeld 13,2 mm
const int KX[5] = {48, 144, 240, 336, 432};           // Mitten, Abstand 16,7 mm
const int KY[2] = {48, 144};
const int BAR_X = 9, BAR_Y = 201, BAR_W = 462, BAR_H = 110;   // Leiste 80,5 x 19,3 mm
const uint16_t COLS[10] = {TFT_BLUE, TFT_RED, TFT_GREEN, TFT_ORANGE, TFT_MAGENTA,
                           TFT_CYAN, TFT_YELLOW, TFT_PINK, TFT_GREENYELLOW, TFT_VIOLET};

void drawKey(int i, bool on) {
  int x = KX[i % 5] - KEY / 2, y = KY[i / 5] - KEY / 2;
  lcd.fillRoundRect(x, y, KEY, KEY, 10, on ? TFT_WHITE : COLS[i]);
  lcd.setTextColor(on ? TFT_BLACK : TFT_WHITE);
  lcd.setTextDatum(textdatum_t::middle_center);
  lcd.setTextSize(3);
  lcd.drawString(String(i + 1), KX[i % 5], KY[i / 5]);
}

void drawLayout() {
  lcd.fillScreen(TFT_BLACK);
  lcd.drawRect(0, 0, lcd.width(), lcd.height(), TFT_DARKGREY);
  for (int i = 0; i < 10; i++) drawKey(i, false);
  lcd.fillRoundRect(BAR_X, BAR_Y, BAR_W, BAR_H, 8, 0x18E3);
  lcd.setTextDatum(textdatum_t::middle_left);
  lcd.setTextColor(TFT_WHITE);
  lcd.setTextSize(2);
  lcd.drawString("Leiste - hier kommen Uhr, Wetter, GIFs", BAR_X + 16, BAR_Y + BAR_H / 2);
}

int keyAt(int x, int y) {
  for (int i = 0; i < 10; i++) {
    int kx = KX[i % 5], ky = KY[i / 5];
    if (abs(x - kx) <= KEY / 2 && abs(y - ky) <= KEY / 2) return i;
  }
  return -1;
}

void calibrate() {
  lcd.fillScreen(TFT_BLACK);
  lcd.setTextDatum(textdatum_t::middle_center);
  lcd.setTextColor(TFT_WHITE);
  lcd.setTextSize(2);
  lcd.drawString("Tippe genau auf die Pfeilspitzen", lcd.width() / 2, lcd.height() / 2);
  lcd.calibrateTouch(cal, TFT_WHITE, TFT_BLACK, 24);
  prefs.putBytes("cal", cal, sizeof(cal));
  Serial.print("Kalibrierwerte: {");
  for (int i = 0; i < 8; i++) Serial.printf("%u%s", cal[i], i < 7 ? ", " : "}\n");
}

void setup() {
  Serial.begin(115200);
  delay(800);
  lcd.init();
  lcd.setRotation(1);
  prefs.begin("deck", false);
  int32_t tx, ty;
  bool force = lcd.getTouch(&tx, &ty);                 // Display beim Start gedrueckt -> neu kalibrieren
  if (!force && prefs.getBytesLength("cal") == sizeof(cal)) {
    prefs.getBytes("cal", cal, sizeof(cal));
    lcd.setTouchCalibrate(cal);
    Serial.println("Gespeicherte Kalibrierung geladen.");
  } else {
    calibrate();
  }
  drawLayout();
}

int lastKey = -1;
uint32_t lastChange = 0;

void loop() {
  int32_t x, y;
  int k = -1;
  if (lcd.getTouch(&x, &y)) {
    k = keyAt(x, y);
    if (k < 0) lcd.fillCircle(x, y, 2, TFT_YELLOW);
  }
  if (k != lastKey && millis() - lastChange > 40) {
    if (lastKey >= 0) drawKey(lastKey, false);
    if (k >= 0) { drawKey(k, true); Serial.printf("Taste %d gedrueckt\n", k + 1); }
    lastKey = k;
    lastChange = millis();
  }
  delay(5);
}
