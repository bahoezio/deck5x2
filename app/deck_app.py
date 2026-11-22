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

import webview

from deck import actions, config
from deck.serial_link import DeckLink

APP_NAME = "Deck 5x2"
APP_VERSION = "0.2.0"

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


# ---------------------------------------------------------------- App-Zustand
class DeckApp:
    def __init__(self):
        self.cfg = config.load()
        self.window = None
        self.quitting = False
        self.last_key = {"i": -1, "at": 0.0}
        self.last_message = ""
        self.cal_values = None
        self.link = DeckLink(on_key=self.on_key, on_status=self.on_status, on_message=self.on_message)
        self.link.time_sync = self.cfg["time_sync"]
        self.link.set_on_connect([config.device_layout(self.cfg)])

    # ---- Ereignisse vom Deck
    def on_key(self, i: int, down: bool):
        if not (0 <= i < config.NUM_KEYS):
            return
        if down:
            self.last_key = {"i": i, "at": time.time()}
            ok, msg = actions.run_action(self.cfg["keys"][i]["action"])
            if msg:
                self.last_message = msg if ok else "⚠ " + msg
            log.info("Taste %d: %s", i + 1, msg or "ok")

    def on_status(self, status):
        log.info("Status: %s", status)

    def on_message(self, msg):
        if msg.get("t") == "cal":
            self.cal_values = msg.get("v")
            self.last_message = "Kalibrierung gespeichert"


class Api:
    """Diese Funktionen ruft die Oberflaeche (ui/index.html) per JavaScript auf."""

    def __init__(self, app: DeckApp):
        self._app = app

    def get_state(self):
        a = self._app
        return {
            "config": a.cfg,
            "status": a.link.status(),
            "lastKey": a.last_key,
            "message": a.last_message,
            "calValues": a.cal_values or a.link.info.get("cal_values"),
            "version": APP_VERSION,
        }

    def save(self, cfg):
        a = self._app
        old_autostart = a.cfg.get("autostart")
        a.cfg = config.save(cfg)
        a.link.time_sync = a.cfg["time_sync"]
        a.link.set_on_connect([config.device_layout(a.cfg)])
        sent = a.link.send(config.device_layout(a.cfg))
        if a.cfg["autostart"] != old_autostart:
            try:
                set_autostart(a.cfg["autostart"])
            except OSError as e:
                log.warning("Autostart konnte nicht gesetzt werden: %s", e)
        a.last_message = "Gespeichert und ans Deck geschickt" if sent else "Gespeichert (Deck nicht verbunden)"
        return {"ok": True, "sent": sent, "config": a.cfg}

    def test_key(self, i):
        ok, msg = actions.run_action(self._app.cfg["keys"][int(i)]["action"])
        return {"ok": ok, "message": msg}

    def calibrate(self):
        sent = self._app.link.send({"t": "calibrate"})
        self._app.last_message = ("Tippe auf dem Deck die 4 Pfeilspitzen an" if sent
                                  else "Deck nicht verbunden")
        return {"ok": sent}

    def read_calibration(self):
        return {"ok": self._app.link.send({"t": "getcal"})}

    def sync_time(self):
        return {"ok": self._app.link.send_time()}

    def choose_program(self):
        w = self._app.window
        if not w:
            return ""
        res = w.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
                                   file_types=("Programme (*.exe;*.lnk;*.bat)", "Alle Dateien (*.*)"))
        return res[0] if res else ""

    def open_log(self):
        try:
            os.startfile(str(log_file))   # nur Windows
        except Exception:
            pass

    def hide(self):
        if self._app.window:
            self._app.window.hide()


# ---------------------------------------------------------------- Infobereich-Symbol
def make_tray(app: DeckApp):
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
    app = DeckApp()
    app.link.start()
    tray = make_tray(app)

    api = Api(app)
    html = config.resource_path("ui/index.html")
    app.window = webview.create_window(APP_NAME, url=str(html), js_api=api, width=1180, height=760,
                                       min_size=(900, 620), background_color="#0E1116", hidden=hidden)

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
