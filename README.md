# Deck 5x2

Ein selbst gebautes Makro-Deck: 10 Tasten aus klarem UV-Harz über einem 4,0″-Touchdisplay, darunter eine breite Leiste für Uhrzeit, Wetter oder GIFs. Gesteuert von einem ESP32-S3, eingestellt über eine Windows-App.

> **Status:** Prototyp. Firmware und App funktionieren, das Gehäuse ist Entwurf v0.2.

## Was es kann

- **10 frei belegbare Tasten:** Programme starten, Webseiten öffnen, Tastenkürzel, Medien-Steuerung, Text tippen
- **Leiste** mit Uhrzeit und Datum (kommt von der App oder optional über WLAN)
- **Windows-App** zum Einstellen: Beschriftung, Farbe und Aktion je Taste, Touch-Kalibrierung, Autostart
- **Ohne App** sendet das Deck F13–F22 wie eine normale Tastatur

## Teile

| Teil | Hinweis |
|---|---|
| ESP32-S3 DevKitC, **N16R8** | 16 MB Flash, 8 MB PSRAM |
| LAFVIN 4,0″ SPI-Display, **ST7796S + XPT2046** | resistiver Touch, 480 × 320 |
| 13 Dupont-Kabel Buchse–Buchse | im Gehäuse später angelötet |
| UV-Harz, kristallklar + UV-Lampe | für die Tasten |
| PLA/PETG, TPU 95A | Gehäuse und Federmatte |

## Verkabelung

| Display | ESP32-S3 |
|---|---|
| VCC | 3V3 |
| GND | GND |
| CS | 10 |
| RESET | 14 |
| DC/RS | 9 |
| SDI(MOSI) | 11 |
| SCK | 12 |
| LED | 3V3 |
| SDO(MISO) | – |
| T_CLK | 4 |
| T_CS | 5 |
| T_DIN | 6 |
| T_DO | 7 |
| T_IRQ | – (wird nicht benutzt) |

## Firmware aufspielen

1. Arduino IDE installieren, Boardpaket **esp32 by Espressif Systems** und die Bibliotheken **LovyanGFX** und **ArduinoJson** installieren.
2. `firmware/deck_firmware/deck_firmware.ino` öffnen.
3. Unter *Tools*: Board **ESP32S3 Dev Module**, USB Mode **USB-OTG (TinyUSB)**, USB CDC On Boot **Enabled**, Flash Size **16MB**, PSRAM **OPI PSRAM**, Partition **16M Flash (3MB APP/9.9MB FATFS)**.
4. USB-Kabel an die Buchse **USB** (nicht COM) und hochladen. Klappt es nicht: BOOT halten, RST kurz drücken, BOOT loslassen.
5. Beim ersten Start vier Pfeile antippen (Touch-Kalibrierung).

Hilfsprogramme zum Testen liegen in `firmware/tools/`.

## App

Die fertige **Deck5x2.exe** gibt es unter [Releases](../../releases). Starten, fertig: Die App findet das Deck automatisch und läuft danach im Infobereich neben der Uhr weiter.

Selbst starten (für Entwickler):

```
cd app
pip install -r requirements.txt
python deck_app.py
```

## Gehäuse

Druckdateien und die interaktive Bauanleitung liegen in `hardware/`.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
