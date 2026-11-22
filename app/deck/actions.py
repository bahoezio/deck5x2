"""Fuehrt aus, was eine Deck-Taste tun soll: Programm starten, Webseite oeffnen, Tastenkuerzel ..."""
import logging
import os
import shlex
import subprocess
import sys
import time
import webbrowser

log = logging.getLogger("deck.actions")

try:
    from pynput.keyboard import Controller, Key
    _kb = Controller()
except Exception:                      # z. B. auf einem Server ohne Desktop
    Controller = Key = None
    _kb = None

MEDIA = {
    "play_pause": "media_play_pause",
    "next": "media_next",
    "previous": "media_previous",
    "volume_up": "media_volume_up",
    "volume_down": "media_volume_down",
    "mute": "media_volume_mute",
}

# Namen, die man in einem Tastenkuerzel schreiben darf, z. B. "Strg+Umschalt+M"
KEY_NAMES = {
    "ctrl": "ctrl", "strg": "ctrl", "control": "ctrl",
    "shift": "shift", "umschalt": "shift", "alt": "alt", "altgr": "alt_gr",
    "win": "cmd", "windows": "cmd", "cmd": "cmd",
    "enter": "enter", "eingabe": "enter", "esc": "esc", "tab": "tab", "space": "space", "leertaste": "space",
    "backspace": "backspace", "entf": "delete", "delete": "delete", "einfg": "insert", "insert": "insert",
    "pos1": "home", "home": "home", "ende": "end", "end": "end", "bildauf": "page_up", "bildab": "page_down",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "druck": "print_screen", "print": "print_screen",
    "mediaplay": "media_play_pause", "mute": "media_volume_mute",
}
for n in range(1, 25):
    KEY_NAMES[f"f{n}"] = f"f{n}"


# System-Aktionen: (Anzeigename, Art, Wert)
SYSTEM = {
    "lock": ("PC sperren", "cmd", ["rundll32.exe", "user32.dll,LockWorkStation"]),
    "taskmgr": ("Task-Manager", "hotkey", "Strg+Umschalt+Esc"),
    "desktop": ("Desktop anzeigen", "hotkey", "Win+D"),
    "explorer": ("Explorer", "hotkey", "Win+E"),
    "screenshot": ("Bildschirmausschnitt", "hotkey", "Win+Umschalt+S"),
    "settings": ("Einstellungen", "hotkey", "Win+I"),
    "clipboard": ("Zwischenablage-Verlauf", "hotkey", "Win+V"),
    "emoji": ("Emoji-Auswahl", "hotkey", "Win+."),
    "calc": ("Rechner", "cmd", ["calc.exe"]),
}


def parse_hotkey(text: str):
    """'Strg+Umschalt+M' -> Liste von pynput-Tasten. Gibt None zurueck, wenn etwas unbekannt ist."""
    if Key is None:
        return None
    parts = [p.strip().lower() for p in text.replace(" ", "").split("+") if p.strip()]
    keys = []
    for p in parts:
        if p in KEY_NAMES:
            k = getattr(Key, KEY_NAMES[p], None)
            if k is None:
                return None
            keys.append(k)
        elif len(p) == 1:
            keys.append(p)
        else:
            return None
    return keys or None


def run_action(action: dict) -> tuple[bool, str]:
    """Fuehrt eine Aktion aus. Rueckgabe: (erfolgreich, Meldung fuer die Oberflaeche)."""
    action = action or {}
    t = action.get("type", "none")
    v = str(action.get("value", "")).strip() if not isinstance(action.get("value"), list) else ""
    try:
        if t == "none":
            return True, ""
        if t == "program":
            if not v:
                return False, "Kein Programm ausgewaehlt"
            if sys.platform == "win32" and os.path.exists(v):
                os.startfile(v)                           # .exe, .lnk, Ordner, Dateien
            else:
                subprocess.Popen(shlex.split(v, posix=(sys.platform != "win32")))
            return True, f"Gestartet: {os.path.basename(v)}"
        if t == "website":
            url = v if "://" in v else "https://" + v
            webbrowser.open(url)
            return True, f"Geoeffnet: {url}"
        if t == "media":
            name = MEDIA.get(v)
            if not name or _kb is None:
                return False, "Medientaste nicht verfuegbar"
            k = getattr(Key, name)
            _kb.press(k); _kb.release(k)
            return True, ""
        if t == "hotkey":
            keys = parse_hotkey(v)
            if not keys or _kb is None:
                return False, f"Unbekanntes Tastenkuerzel: {v}"
            for k in keys:
                _kb.press(k)
            for k in reversed(keys):
                _kb.release(k)
            return True, ""
        if t == "system":
            if v not in SYSTEM:
                return False, f"Unbekannte Systemaktion: {v}"
            name, kind, val = SYSTEM[v]
            if kind == "cmd":
                subprocess.Popen(val, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return True, name
            return run_action({"type": "hotkey", "value": val})
        if t == "multi":
            steps = action.get("value") if isinstance(action.get("value"), list) else []
            for st in steps:
                if st.get("type") == "delay":
                    time.sleep(max(0, min(60000, int(float(st.get("value") or 0)))) / 1000)
                else:
                    ok, msg = run_action(st)
                    if not ok:
                        return False, msg
                    time.sleep(0.03)
            return True, f"Multi-Aktion ({len(steps)} Schritte)"
        if t == "text":
            if _kb is None:
                return False, "Tastatur nicht verfuegbar"
            _kb.type(v)
            return True, ""
        return False, f"Unbekannte Aktion: {t}"
    except Exception as e:                                 # nie die App abstuerzen lassen
        log.exception("Aktion fehlgeschlagen")
        return False, f"Fehler: {e}"
