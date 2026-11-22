"""Deck 5x2 - Windows-App.

Startet das Einstellungsfenster und laeuft danach im Infobereich (neben der Uhr) weiter:
- verbindet sich automatisch mit dem Deck ueber USB
- fuehrt die Aktionen der Tasten aus
- stellt die Uhrzeit im Deck
"""
import logging
import os
import socket
import sys
import threading
import time
from logging.handlers import RotatingFileHandler



def _unblock_files():
    """Heruntergeladene ZIPs markiert Windows als 'aus dem Internet'. Dann weigert sich .NET,
    die DLLs fuer das Fenster zu laden. Die Markierung im eigenen Ordner entfernen."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    for root, _dirs, files in os.walk(base):
        for name in files:
            if name.lower().endswith((".dll", ".pyd", ".exe")):
                try:
                    os.remove(os.path.join(root, name) + ":Zone.Identifier")
                except OSError:
                    pass


_unblock_files()
import webview  # noqa: E402

import json

from deck import actions, config, icons, render, widgets
from deck.engine import Engine, window_apps

APP_NAME = "Deck 5x2"
APP_VERSION = "0.3.0"

# ---------------------------------------------------------------- Logging
log_file = config.config_dir() / "deck.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[RotatingFileHandler(log_file, maxBytes=500_000, backupCount=1, encoding="utf-8"),
              logging.StreamHandler(sys.stdout) if sys.stdout else logging.NullHandler()],
)
log = logging.getLogger("deck")


# ---------------------------------------------------------------- Autostart (Windows)
def set_autostart(enabled: bool):
    if sys.platform != "win32":
        return
    import winreg
    key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    exe = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" "{os.path.abspath(__file__)}"'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            cmd = f'"{exe}" --hidden' if getattr(sys, "frozen", False) else f"{exe} --hidden"
            winreg.SetValueEx(k, "Deck5x2", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, "Deck5x2")
            except FileNotFoundError:
                pass


# ---------------------------------------------------------------- Schnittstelle fuer die Oberflaeche
class Api:
    """Diese Funktionen ruft die Oberflaeche (ui/index.html) per JavaScript auf."""

    def __init__(self, app: Engine):
        self._app = app
        self._window = None

    # ---- Zustand
    def get_state(self):
        a = self._app
        return {
            "config": a.cfg,
            "status": a.link.status(),
            "lastKey": a.last_key,
            "message": a.last_message,
            "calValues": a.cal_values or a.link.info.get("cal_values"),
            "version": APP_VERSION,
            "page": a.page_id,
            "iconEpoch": a.icon_epoch,
        }

    def poll(self):
        a = self._app
        t, a.touches = a.touches, []
        return {"status": a.link.status(), "lastKey": a.last_key, "message": a.last_message, "page": a.page_id,
                "calValues": a.cal_values, "iconEpoch": a.icon_epoch, "touches": t}

    def get_glyphs(self):
        return {"glyphs": icons.GLYPHS, "font": render.has_font("icons"), "system": [[k, v[0]] for k, v in actions.SYSTEM.items()]}

    # ---- Speichern / Vorschau
    def save(self, cfg):
        a = self._app
        old_autostart = a.cfg.get("autostart")
        sent = a.apply_config(cfg)
        if a.cfg["autostart"] != old_autostart:
            try:
                set_autostart(a.cfg["autostart"])
            except OSError as e:
                log.warning("Autostart konnte nicht gesetzt werden: %s", e)
        a.last_message = "Gespeichert und ans Deck geschickt" if sent else "Gespeichert (Deck nicht verbunden)"
        return {"ok": True, "sent": sent, "config": a.cfg}

    def preview_key(self, key, toggled=False):
        try:
            return self._app.preview_key(key, toggled)
        except Exception:
            log.exception("Vorschau fehlgeschlagen")
            return ""

    def preview_bar(self, zones):
        try:
            return self._app.preview_bar(zones)
        except Exception:
            log.exception("Vorschau Leiste fehlgeschlagen")
            return []

    def goto_page(self, pid):
        self._app.goto(pid)
        return {"ok": True}

    def test_key(self, pid, i):
        page = config.page_by_id(self._app.cfg, pid)
        _, action = self._app.key_look(page, int(i))
        if action["type"] == "page":
            self._app.page_action(action["value"])
            return {"ok": True, "message": "Seite gewechselt"}
        ok, msg = actions.run_action(action)
        return {"ok": ok, "message": msg}

    # ---- Dateien
    def _dialog(self, types, save=False, name=""):
        w = self._window
        if not w:
            return ""
        if save:
            res = w.create_file_dialog(webview.SAVE_DIALOG, save_filename=name, file_types=types)
            return res if isinstance(res, str) else (res[0] if res else "")
        res = w.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=types)
        return res[0] if res else ""

    def choose_program(self):
        return self._dialog(("Programme (*.exe;*.lnk;*.bat;*.cmd)", "Alle Dateien (*.*)"))

    def choose_image(self, gif_only=False):
        types = ("GIF (*.gif)",) if gif_only else ("Bilder (*.png;*.jpg;*.jpeg;*.gif;*.ico;*.bmp;*.webp)", "Alle Dateien (*.*)")
        p = self._dialog(types)
        if not p:
            return ""
        try:
            return icons.import_image(p)
        except OSError as e:
            self._app.last_message = f"⚠ Bild nicht lesbar: {e}"
            return ""

    def export_profile(self):
        p = self._dialog(("Deck-Profil (*.json)",), save=True, name="Deck5x2-Profil.json")
        if not p:
            return {"ok": False}
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self._app.cfg, f, ensure_ascii=False, indent=2)
        return {"ok": True, "path": p}

    def import_profile(self):
        p = self._dialog(("Deck-Profil (*.json)", "Alle Dateien (*.*)"))
        if not p:
            return {"ok": False}
        try:
            with open(p, encoding="utf-8") as f:
                cfg = config.normalize(json.load(f))
        except (OSError, ValueError) as e:
            return {"ok": False, "message": str(e)}
        return {"ok": True, "config": cfg}

    def running_apps(self):
        return window_apps()

    def geocode(self, name):
        try:
            return {"ok": True, "results": widgets.geocode(name)}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    # ---- Touch
    def calibrate(self):
        sent = self._app.link.send({"t": "calibrate"})
        self._app.last_message = "Tippe auf dem Deck die 4 Pfeilspitzen an" if sent else "Deck nicht verbunden"
        return {"ok": sent}

    def read_calibration(self):
        return {"ok": self._app.link.send({"t": "getcal"})}

    def restore_calibration(self):
        v = self._app.cfg.get("cal_backup")
        if not v:
            return {"ok": False, "message": "Keine gesicherten Werte"}
        return {"ok": self._app.link.send({"t": "setcal", "v": v})}

    def backup_calibration(self):
        v = self._app.cal_values
        if not v:
            return {"ok": False, "message": "Erst Werte lesen"}
        self._app.cfg["cal_backup"] = [int(x) for x in v]
        self._app.cfg = config.save(self._app.cfg)
        return {"ok": True, "config": self._app.cfg}

    def touch_test(self, on):
        a = self._app
        a.touch_test = bool(on)
        a.touches = []
        ok = a.link.send({"t": "touchtest", "on": bool(on)})
        if not on:
            a.poke()
        return {"ok": ok}

    def deck_sleep(self):
        return {"ok": self._app.link.send({"t": "sleep", "on": True})}

    def sync_time(self):
        return {"ok": self._app.link.send_time()}

    def open_log(self):
        try:
            os.startfile(str(log_file))   # nur Windows
        except Exception:
            pass

    def hide(self):
        if self._window:
            self._window.hide()


# ---------------------------------------------------------------- Infobereich-Symbol
def make_tray(app: Engine):
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        log.warning("pystray nicht verfuegbar, kein Symbol im Infobereich")
        return None
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 8, 62, 56), 10, fill=(20, 24, 31, 255))
    for r in range(2):
        for c in range(3):
            d.rounded_rectangle((9 + c * 17, 14 + r * 15, 22 + c * 17, 26 + r * 15), 3, fill=(60, 196, 211, 255))
    d.rounded_rectangle((9, 44, 55, 50), 2, fill=(120, 130, 145, 255))

    def show(icon, item):
        if app.window:
            app.window.show()
            app.window.restore()

    def quit_app(icon, item):
        app.quitting = True
        icon.stop()
        app.link.stop()
        if app.window:
            app.window.destroy()

    menu = pystray.Menu(pystray.MenuItem("Einstellungen öffnen", show, default=True),
                        pystray.MenuItem("Beenden", quit_app))
    icon = pystray.Icon("Deck5x2", img, APP_NAME, menu)
    icon.run_detached()
    return icon


# ---------------------------------------------------------------- Start
def single_instance():
    """Verhindert, dass die App zweimal laeuft (sonst streiten sich beide um das Deck)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 47821))
        return s
    except OSError:
        return None


def main():
    lock = single_instance()
    if lock is None:
        log.info("Deck-App laeuft bereits")
        return
    hidden = "--hidden" in sys.argv
    app = Engine()
    app.window = None
    app.quitting = False
    app.start()
    tray = make_tray(app)

    api = Api(app)
    html = config.resource_path("ui/index.html")
    app.window = webview.create_window(APP_NAME, url=str(html), js_api=api, width=1280, height=820,
                                       min_size=(980, 640), background_color="#0E1116", hidden=hidden)
    api._window = app.window

    def on_closing():
        if app.quitting or tray is None:
            app.link.stop()
            return True
        app.window.hide()                    # Fenster schliessen = im Hintergrund weiterlaufen
        return False

    app.window.events.closing += on_closing
    webview.start(debug=("--debug" in sys.argv), http_server=True)   # Seite ueber http://127.0.0.1 laden
    app.link.stop()
    if tray:
        tray.stop()


if __name__ == "__main__":
    main()
