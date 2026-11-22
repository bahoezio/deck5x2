# Protokoll zwischen Deck und App (Firmware 0.3)

Das Deck meldet sich am PC gleichzeitig als **Tastatur** und als **serielle Schnittstelle** (USB-CDC).
Über die serielle Schnittstelle tauschen Deck und App Nachrichten aus: eine JSON-Zeile pro Nachricht, abgeschlossen mit `\n`.
Nach `img` und `anim` folgen direkt `n` Bytes Bilddaten.

## Deck → App

| Nachricht | Bedeutung |
|---|---|
| `{"t":"hello","fw":"0.3.0","keys":10,"cal":true,"caps":["img","anim","rle","touch","sleep"],"light":false}` | Antwort auf `hello?` und nach dem Start |
| `{"t":"key","i":0,"down":true}` | Taste `i` (0–9) gedrückt (`down:false` = losgelassen) |
| `{"t":"tap","x":120,"y":250}` | Auf die Leiste getippt |
| `{"t":"swipe","dir":"left"}` | Auf der Leiste gewischt (`left`/`right`) |
| `{"t":"touch","x":10,"y":20}` / `{"t":"touch","up":true}` | Nur im Touch-Test: jede Berührung |
| `{"t":"wake"}` | Bildschirmschoner durch Antippen beendet |
| `{"t":"cal","v":[…8 Zahlen…]}` | Aktuelle Touch-Kalibrierung |
| `{"t":"ok","for":"img","ok":true}` | Bestätigung |

## App → Deck

| Nachricht | Bedeutung |
|---|---|
| `{"t":"hello?"}` | Wer bist du? |
| `{"t":"hb"}` | Herzschlag, alle 2 s. Bleibt er 6 s aus, zeichnet das Deck selbst und sendet F13–F22. |
| `{"t":"time","local":1795360000}` | Lokale Zeit in Sekunden (Sommerzeit eingerechnet) |
| `{"t":"layout","keys":[{"text":"Spotify","color":"#1DB954"}, …]}` | Beschriftung für den Betrieb ohne App, wird gespeichert |
| `{"t":"screen","app":true}` | Ab jetzt zeigt das Deck die Bilder der App |
| `{"t":"img","x":10,"y":10,"w":76,"h":76,"z":1,"n":1560}` + Bytes | Bild an Position x/y |
| `{"t":"anim","slot":0,"x":9,"y":201,"w":228,"h":110,"frames":24,"ms":[80,…],"z":1,"n":…}` + Bytes | Animation (GIF), 4 Plätze |
| `{"t":"anim","slot":0,"stop":true}` | Animation anhalten |
| `{"t":"cfg","sleep_s":600,"bright":100}` | Bildschirmschoner (0 = aus) und Helligkeit |
| `{"t":"sleep","on":true}` | Display sofort schlafen legen |
| `{"t":"touchtest","on":true}` | Touch-Test an/aus |
| `{"t":"calibrate"}` / `{"t":"getcal"}` / `{"t":"setcal","v":[…]}` | Kalibrierung |

## Bilddaten

Pixel als RGB565, höherwertiges Byte zuerst, zeilenweise. Mit `"z":1` lauflängenkodiert:
ein Steuerbyte `c < 128` heißt „`c+1` Pixel folgen unverändert“, `c ≥ 128` heißt „das nächste Pixel `c-126`-mal wiederholen“.
Bei `anim` stehen alle Bilder direkt hintereinander.

## Ohne App

Läuft keine App, zeichnet das Deck Beschriftung, Farbe und Uhr selbst und sendet für die Tasten 1–10 die Tasten **F13 bis F22**.
