// Deck 5x2 - Display- und Touch-Test
// Display: LAFVIN 4,0" ST7796S (480x320), Touch: XPT2046
// Board:   ESP32-S3 DevKitC N16R8
//
// Was du sehen solltest:
//  - einen 1-Pixel-Rahmen in Weiss genau am Rand des Bildbereichs
//  - ein gelbes "A" oben links (zeigt, wie das Bild gedreht ist)
//  - drei Farbfelder: Rot, Gruen, Blau
//  - beim Tippen mit dem Stift: gelbe Punkte und Messwerte im Seriellen Monitor (115200 Baud)
//
// Probleme:
//  - Farben negativ (Schwarz ist weiss)  -> unten cfg.invert = true;
//  - Rot und Blau vertauscht             -> unten cfg.rgb_order = true;
//  - Bild flackert oder hat Fehler       -> freq_write auf 20000000 senken

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
      cfg.pin_int = 15;                     // T_IRQ
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

void drawTestScreen() {
  lcd.fillScreen(TFT_BLACK);
  // 1-Pixel-Rahmen genau am Rand
  lcd.drawRect(0, 0, lcd.width(), lcd.height(), TFT_WHITE);
  // Ecken-Markierungen, damit der Rahmen leichter zu finden ist
  int L = 20;
  lcd.drawFastHLine(0, 0, L, TFT_RED);                     lcd.drawFastVLine(0, 0, L, TFT_RED);
  lcd.drawFastHLine(lcd.width() - L, lcd.height() - 1, L, TFT_RED);
  lcd.drawFastVLine(lcd.width() - 1, lcd.height() - L, L, TFT_RED);
  // Orientierung
  lcd.setTextColor(TFT_YELLOW);
  lcd.setTextSize(3);
  lcd.drawString("A", 10, 10);
  // Farbfelder
  lcd.fillRect(60,  110, 110, 70, TFT_RED);
  lcd.fillRect(185, 110, 110, 70, TFT_GREEN);
  lcd.fillRect(310, 110, 110, 70, TFT_BLUE);
  lcd.setTextSize(2);
  lcd.setTextColor(TFT_WHITE);
  lcd.drawString("Deck 5x2 - Display-Test", 60, 50);
  lcd.setTextColor(TFT_LIGHTGREY);
  lcd.drawString("Mit dem Stift tippen", 60, 220);
  lcd.drawString("Doppeltipp oben rechts: loeschen", 60, 250);
}

void setup() {
  Serial.begin(115200);
  delay(800);
  Serial.println("Display-Test startet ...");
  lcd.init();
  lcd.setRotation(1);          // Querformat 480 x 320
  drawTestScreen();
  Serial.printf("Bildgroesse: %d x %d Pixel\n", lcd.width(), lcd.height());
}

uint32_t lastPrint = 0, lastCornerTap = 0;

void loop() {
  int32_t x, y;
  if (lcd.getTouch(&x, &y)) {
    lcd.fillCircle(x, y, 3, TFT_YELLOW);
    if (millis() - lastPrint > 120) {
      lgfx::touch_point_t raw;
      lcd.getTouchRaw(&raw, 1);
      Serial.printf("Touch  x=%3d  y=%3d   roh: %4d / %4d\n", (int)x, (int)y, raw.x, raw.y);
      lastPrint = millis();
    }
    // Doppeltipp oben rechts loescht die Punkte
    if (x > lcd.width() - 60 && y < 60) {
      if (millis() - lastCornerTap < 600 && millis() - lastCornerTap > 150) drawTestScreen();
      lastCornerTap = millis();
    }
  }
  delay(5);
}
