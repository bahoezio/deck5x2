# Protokoll zwischen Deck und App

Das Deck meldet sich am PC gleichzeitig als **Tastatur** und als **serielle Schnittstelle** (USB-CDC).
Über die serielle Schnittstelle tauschen Deck und App Nachrichten aus: eine JSON-Zeile pro Nachricht, abgeschlossen mit `\n`.

## Deck → App

| Nachricht | Bedeutung |
|---|---|
| `{"t":"hello","fw":"0.2.0","device":"Deck 5x2","keys":10,"cal":true}` | Antwort auf `hello?` und nach dem Start |
| `{"t":"key","i":0,"down":true}` | Taste `i` (0–9) gedrückt (`down:false` = losgelassen) |
| `{"t":"cal","v":[…8 Zahlen…]}` | Aktuelle Touch-Kalibrierung |
| `{"t":"ok","for":"layout"}` | Bestätigung |

## App → Deck

| Nachricht | Bedeutung |
|---|---|
| `{"t":"hello?"}` | Wer bist du? |
| `{"t":"hb"}` | Herzschlag, alle 2 s. Bleibt er 6 s aus, sendet das Deck wieder F13–F22. |
| `{"t":"time","local":1795360000}` | Lokale Zeit in Sekunden (Sommerzeit eingerechnet) |
| `{"t":"layout","keys":[{"text":"Spotify","color":"#1DB954"}, …]}` | Beschriftung und Farbe der 10 Tasten, wird im Deck gespeichert |
| `{"t":"calibrate"}` | Kalibrierung mit 4 Pfeilen auf dem Deck starten |
| `{"t":"getcal"}` | Kalibrierung abfragen |
| `{"t":"setcal","v":[…8 Zahlen…]}` | Kalibrierung setzen (z. B. Standardwerte) |

## Ohne App

Läuft keine App, verhält sich das Deck wie eine normale Tastatur und sendet für die Tasten 1–10 die Tasten **F13 bis F22**.
