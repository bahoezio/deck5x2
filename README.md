# Deck 5x2

Ein selbst gebautes Makro-Deck: 10 Tasten aus klarem UV-Harz über einem 4,0″-Touchdisplay, darunter eine breite Leiste für Uhrzeit, Wetter oder GIFs. Gesteuert von einem ESP32-S3, eingestellt über eine Windows-App.

> **Status:** Prototyp. Firmware 0.3 und App 0.3, das Gehäuse ist Entwurf v0.2.

## Was es kann

- **10 Tasten mit Icons:** eigene Bilder und GIFs, Symbole, Emoji oder automatisch das Programm-Icon bzw. Logo der Webseite
- **Aktionen:** Programme, Webseiten, Tastenkürzel, Medien, Text tippen, System (PC sperren, Task-Manager …), Multi-Aktionen
- **Seiten und Ordner**, Wischen auf der Leiste wechselt die Seite
- **Profile je Programm:** ist z. B. Spotify im Vordergrund, springt das Deck auf deine Spotify-Seite
- **Umschalt-Tasten** mit zwei Zuständen, **lang drücken** als zweite Aktion, **Live-Tasten** (Uhr, CPU, Zähler, Stoppuhr)
- **Leiste** in bis zu 4 Bereiche geteilt: Uhr, Wetter, „läuft gerade“ mit Cover, CPU/RAM, Text oder GIF
- **Touch:** Kalibrierung mit gesicherten Werten, Touch-Test, Bildschirmschoner
- **Ohne App** zeigt das Deck Beschriftung und Uhr und sendet F13–F22 wie eine normale Tastatur

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

Die fertige App gibt es unter [Releases](../../releases): ZIP entpacken und **Deck5x2.exe** im Ordner starten. Die App findet das Deck automatisch und läuft danach im Infobereich neben der Uhr weiter.

Selbst starten (für Entwickler):

```
cd app
pip install -r requirements.txt
python deck_app.py
```

Ohne Deck testen: `python tools/ui_dev_server.py` startet die Oberfläche im Browser mit einem simulierten Deck.

## Gehäuse

Druckdateien und die interaktive Bauanleitung liegen in `hardware/`.

**v0.3** (`deck_v03_2_gehaeuse.3mf`): 30° Neigung, Oberschale wie v0.2, neue Unterschale.
Der ESP liegt hinten auf einer 18 mm breiten Auflage (mit 1 mm Klebepad), die Dupont-Stecker hängen links und rechts daneben.
Unter der Stiftleiste des Displays ist keine Auflage, die Stecker haben dort ca. 7 mm Platz nach unten.
Schrauben: 4 × M3 × 8 von unten bzw. hinten durch die Unterschale und die Display-Platine in die Gewindeeinsätze der Oberschale.
Die Unterschale wird aus `hardware/src/unterschale_v03.py` erzeugt (Parameter oben in der Datei).

## Lizenz

MIT, siehe [LICENSE](LICENSE).
