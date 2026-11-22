"""Das Herz der App: welche Seite gerade angezeigt wird, was beim Druecken passiert,
und welche Bilder ans Deck muessen."""
import copy
import datetime as dt
import json
import logging
import sys
import threading
import time
import webbrowser

from PIL import ImageChops

from . import actions, config, icons, render, widgets
from .serial_link import DeckLink

log = logging.getLogger("deck.engine")

HOLD_S = 0.5
BAR_ANIM_SLOT = 0
KEY_ANIM_SLOTS = [1, 2, 3]
BAR_ANIM_BYTES = 2_600_000
KEY_ANIM_BYTES = 700_000


def foreground_exe() -> str:
    """Name des Programms im Vordergrund, z. B. 'spotify.exe' (nur Windows)."""
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        import psutil
        return psutil.Process(pid.value).name().lower()
    except Exception:
        return ""


def window_apps() -> list[str]:
    """Programme mit sichtbarem Fenster (fuer die Profil-Auswahl)."""
    names = set()
    try:
        import psutil
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            pids = set()

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def cb(hwnd, _):
                if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    pids.add(pid.value)
                return True

            user32.EnumWindows(cb, 0)
            for pid in pids:
                try:
                    names.add(psutil.Process(pid).name().lower())
                except Exception:
                    pass
        else:
            for p in psutil.process_iter(["name"]):
                if p.info["name"]:
                    names.add(p.info["name"].lower())
    except Exception:
        pass
    skip = {"explorer.exe", "deck5x2.exe", "textinputhost.exe", "applicationframehost.exe", "systemsettings.exe",
            "shellexperiencehost.exe", "searchhost.exe", "startmenuexperiencehost.exe", "python.exe", "pythonw.exe"}
    return sorted(n for n in names if n not in skip)


class Engine:
    def __init__(self):
        self.cfg = config.load()
        self.ctx = widgets.Context()
        self.lock = threading.RLock()
        self.page_id = self.cfg["pages"][0]["id"]
        self.nav = []                                   # Verlauf fuer "Zurueck"
        self.toggles = {}                               # (seite, taste) -> an/aus
        self.live = {}                                  # (seite, taste) -> Zaehler/Stoppuhr
        self.last_key = {"i": -1, "at": 0.0, "page": ""}
        self.last_message = ""
        self.cal_values = None
        self.icon_epoch = 0
        self.touches = []
        self.touch_test = False
        self.profile_from = None                        # Seite vor dem automatischen Wechsel
        self.profile_page = None
        self._last_fg = ""
        self._hold = {}
        self._sent_keys = {}
        self._sent_zones = {}
        self._zone_imgs = {}                            # zuletzt gesendetes Bild je Bereich (fuer Teil-Updates)
        self._sent_anims = {}
        self._need_full = True
        self._transition = None
        self._wake = threading.Event()
        self.link = DeckLink(on_key=self.on_key, on_status=self.on_status, on_message=self.on_message)
        self.link.time_sync = self.cfg["time_sync"]
        self.link.set_on_connect([config.device_layout(self.cfg)])

    # ------------------------------------------------------------------ Start / Stopp
    def start(self):
        self.link.start()
        threading.Thread(target=self._worker, name="deck-render", daemon=True).start()

    def stop(self):
        self.link.stop()

    # ------------------------------------------------------------------ Seiten
    @property
    def page(self):
        return config.page_by_id(self.cfg, self.page_id)

    def goto(self, pid: str, push=True, manual=True):
        with self.lock:
            target = config.page_by_id(self.cfg, pid)["id"]
            if target == self.page_id:
                return
            if push:
                self.nav.append(self.page_id)
                self.nav = self.nav[-20:]
            self.page_id = target
            if manual:
                self.profile_from = None
                self.profile_page = None
            recent = time.time() - self.last_key["at"] < 2.0
            self._transition = {"from": self.last_key["i"] if recent else -1}
        self.poke()

    def page_action(self, value: str):
        ids = [p["id"] for p in self.cfg["pages"]]
        cur = ids.index(self.page_id) if self.page_id in ids else 0
        if value == "__back__":
            if self.nav:
                self.goto(self.nav.pop(), push=False)
            else:
                self.goto(ids[0], push=False)
        elif value == "__home__":
            self.nav.clear()
            self.goto(ids[0], push=False)
        elif value == "__next__":
            self.goto(ids[(cur + 1) % len(ids)])
        elif value == "__prev__":
            self.goto(ids[(cur - 1) % len(ids)])
        else:
            self.goto(value)

    # ------------------------------------------------------------------ Tasten
    def key_state(self, pid, i):
        return self.live.setdefault((pid, i), {"count": 0, "elapsed": 0.0, "started": None})

    def key_look(self, page: dict, i: int):
        """Aussehen einer Taste im aktuellen Zustand (Umschalt-Taste, Live-Wert)."""
        k, owner = config.effective_key(self.cfg, page, i)
        look = {kk: k[kk] for kk in ("text", "color", "text_color", "show_text", "icon", "icon_mode")}
        action = k["action"]
        if k["toggle"]["enabled"] and self.toggles.get((owner, i)):
            tg = k["toggle"]
            look["text"] = tg["text"] or look["text"]
            look["color"] = tg["color"]
            if tg["icon"]["kind"] != "none":
                look["icon"] = tg["icon"]
            if tg["action"]["type"] != "none":
                action = tg["action"]
        if k["live"] != "none":
            txt = widgets.live_text(k["live"], self.ctx, self.key_state(owner, i), dt.datetime.now())
            if txt is not None:
                if k["live"] in ("counter", "stopwatch") and look["text"]:
                    txt = f"{look['text']} {txt}" if k["live"] == "counter" else txt
                look["text"] = txt
                look["show_text"] = True
        return look, action

    def on_key(self, i: int, down: bool):
        if not (0 <= i < config.NUM_KEYS):
            return
        page = self.page
        k, _ = config.effective_key(self.cfg, page, i)
        if down:
            self.last_key = {"i": i, "at": time.time(), "page": page["id"]}
            if k["hold"]["type"] != "none" or k["live"] == "stopwatch":
                t = threading.Timer(HOLD_S, self._fire_hold, args=(page["id"], i))
                self._hold[i] = t
                t.start()
            else:
                self.trigger(page, i)
        else:
            t = self._hold.pop(i, None)
            if t is not None and t.is_alive():
                t.cancel()
                self.trigger(page, i)

    def _fire_hold(self, pid, i):
        self._hold.pop(i, None)
        page = config.page_by_id(self.cfg, pid)
        k, owner = config.effective_key(self.cfg, page, i)
        if k["live"] == "stopwatch" and k["hold"]["type"] == "none":
            self.live[(owner, i)] = {"count": 0, "elapsed": 0.0, "started": None}    # lang druecken = zuruecksetzen
            self.poke()
            return
        self.run(k["hold"], f"Taste {i + 1} (lang)")

    def trigger(self, page: dict, i: int):
        k, owner = config.effective_key(self.cfg, page, i)
        _, action = self.key_look(page, i)
        if k["toggle"]["enabled"]:
            key = (owner, i)
            self.toggles[key] = not self.toggles.get(key, False)
        st = self.key_state(owner, i)
        if k["live"] == "counter":
            st["count"] += 1
        elif k["live"] == "stopwatch":
            if st["started"]:
                st["elapsed"] += time.time() - st["started"]
                st["started"] = None
            else:
                st["started"] = time.time()
        self.run(action, f"Taste {i + 1}")
        self.poke()

    def run(self, action: dict, label=""):
        t = action.get("type", "none")
        if t == "none":
            return
        if t == "page":
            self.page_action(str(action.get("value", "")))
            return
        if t == "system" and action.get("value") == "deck_sleep":
            self.link.send({"t": "sleep", "on": True})
            return
        if t == "multi":
            # Seitenwechsel in einer Multi-Aktion selbst ausfuehren, den Rest wie gewohnt
            steps = action.get("value") or []
            pages = [s for s in steps if s.get("type") == "page"]
            rest = {"type": "multi", "value": [s for s in steps if s.get("type") != "page"]}

            def go():
                ok, msg = actions.run_action(rest)
                for s in pages:
                    self.page_action(str(s.get("value", "")))
                self._report(ok, msg, label)
            threading.Thread(target=go, daemon=True).start()
            return

        def go():
            ok, msg = actions.run_action(action)
            self._report(ok, msg, label)
        threading.Thread(target=go, daemon=True).start()

    def _report(self, ok, msg, label):
        if msg:
            self.last_message = msg if ok else "⚠ " + msg
        log.info("%s: %s", label, msg or "ok")

    # ------------------------------------------------------------------ Ereignisse vom Deck
    def on_status(self, status):
        log.info("Status: %s", status)
        if status.get("connected"):
            self._need_full = True
            self.poke()

    def on_message(self, msg):
        t = msg.get("t")
        if t == "cal":
            self.cal_values = msg.get("v")
            if self.cfg.get("cal_backup") is None and isinstance(self.cal_values, list) and any(self.cal_values):
                self.cfg["cal_backup"] = [int(v) for v in self.cal_values]
                self.cfg = config.save(self.cfg)
        elif t == "touch":
            if len(self.touches) < 4000:
                self.touches.append({"x": msg.get("x"), "y": msg.get("y"), "up": bool(msg.get("up"))})
        elif t == "swipe":
            if self.cfg.get("swipe_pages", True) and len(self.cfg["pages"]) > 1:
                self.page_action("__next__" if msg.get("dir") == "left" else "__prev__")
        elif t == "tap":
            self._bar_tap(int(msg.get("x", 0)), int(msg.get("y", 0)))
        elif t == "wake":
            pass

    def _bar_tap(self, x, y):
        zones = self.cfg["bar"]["zones"]
        rects = render.zone_rects([z["w"] for z in zones])
        for z, (zx, zw) in zip(zones, rects):
            if render.BAR_X + zx - 3 <= x <= render.BAR_X + zx + zw + 3:
                if z["type"] == "nowplaying":
                    actions.run_action({"type": "media", "value": "play_pause"})
                elif z["type"] == "weather" and z["opts"].get("lat") is not None:
                    webbrowser.open(f"https://open-meteo.com/en/docs#latitude={z['opts']['lat']}&longitude={z['opts']['lon']}")
                elif z["type"] == "clock":
                    pass
                return

    # ------------------------------------------------------------------ Einstellungen
    def apply_config(self, cfg: dict):
        with self.lock:
            self.cfg = config.save(cfg)
            ids = {p["id"] for p in self.cfg["pages"]}
            if self.page_id not in ids:
                self.page_id = self.cfg["pages"][0]["id"]
            self.nav = [p for p in self.nav if p in ids]
            self.link.time_sync = self.cfg["time_sync"]
            self.link.set_on_connect([config.device_layout(self.cfg)])
            self._sent_keys.clear()
            self._sent_zones.clear()
        sent = self.link.send(config.device_layout(self.cfg))
        self._send_device_cfg()
        self.poke()
        return sent

    def _send_device_cfg(self):
        self.link.send({"t": "cfg", "sleep_s": int(self.cfg["sleep_min"]) * 60, "bright": int(self.cfg["brightness"]),
                        "fx": bool(self.cfg.get("fx", True))})

    # ------------------------------------------------------------------ Bilder
    def poke(self):
        self._wake.set()

    def key_image(self, page: dict, i: int, scale=1, look=None):
        look, action = (look, page["keys"][i]["action"]) if look else self.key_look(page, i)
        icon = icons.get_icon(look["icon"], action, on_ready=self._icon_ready)
        return render.render_key(look, icon, scale)

    def _icon_ready(self):
        self.icon_epoch += 1
        self._sent_keys.clear()
        self.poke()

    def _key_anim(self, look):
        ic = look.get("icon") or {}
        if ic.get("kind") == "file" and ic.get("value", "").lower().endswith(".gif") and icons.is_animated(ic["value"]):
            return ic["value"]
        return None

    def _send_key_anim(self, slot, path, look, x, y):
        frames = icons.load_frames(path, render.KEY, render.KEY, KEY_ANIM_BYTES,
                                   fit="cover" if look.get("icon_mode") == "full" else "contain")
        if not frames:
            return False
        imgs = []
        for fr, _ in frames:
            imgs.append(render.render_key(look, fr, 1))
        return self._send_anim(slot, x, y, render.KEY, render.KEY, imgs, [ms for _, ms in frames])

    def _send_anim(self, slot, x, y, w, h, imgs, ms):
        raw = b"".join(render.to_rgb565(im) for im in imgs)
        z = render.rle(raw)
        payload, zz = (z, 1) if len(z) < len(raw) else (raw, 0)
        return self.link.send_binary({"t": "anim", "slot": slot, "x": x, "y": y, "w": w, "h": h,
                                      "frames": len(imgs), "ms": ms, "z": zz}, payload)

    def _send_img(self, x, y, img):
        data, z = render.encode(img)
        return self.link.send_binary({"t": "img", "x": x, "y": y, "w": img.width, "h": img.height, "z": z}, data)

    def _refresh(self):
        if not self.link.connected:
            self._sent_keys.clear(); self._sent_zones.clear(); self._sent_anims.clear()
            self._need_full = True
            return
        if not self.link.has("img"):
            return                                       # alte Firmware: nur Beschriftung (layout)
        if self._need_full:
            self._need_full = False
            self._sent_keys.clear(); self._sent_zones.clear(); self._sent_anims.clear()
            self.link.send({"t": "screen", "app": True})
            for s in [BAR_ANIM_SLOT] + KEY_ANIM_SLOTS:
                self.link.send({"t": "anim", "slot": s, "stop": True})
            self._send_device_cfg()
        if self.touch_test:
            return
        now = dt.datetime.now()
        with self.lock:
            page = copy.deepcopy(self.page)
        wanted_anims = {}
        free_slots = list(KEY_ANIM_SLOTS)
        # Seitenwechsel mit Effekt: das Deck sammelt die neuen Tasten und zeigt sie dann als Welle
        trans, self._transition = self._transition, None
        use_fx = trans is not None and self.cfg.get("fx", True) and self.link.has("fx")
        if use_fx:
            self.link.send({"t": "page"})
        # Tasten
        for i in range(config.NUM_KEYS):
            look, action = self.key_look(page, i)
            gif = self._key_anim(look)
            sig = json.dumps([look, action.get("type"), str(action.get("value"))], sort_keys=True) + f"|{self.icon_epoch}"
            x, y = render.key_origin(i)
            if gif and free_slots:
                slot = free_slots.pop(0)
                wanted_anims[slot] = ("key", page["id"], i, sig)
                if self._sent_anims.get(slot) != wanted_anims[slot]:
                    self._send_key_anim(slot, gif, look, x, y)
                    self._sent_anims[slot] = wanted_anims[slot]
                self._sent_keys[i] = sig
                continue
            if self._sent_keys.get(i) != sig:
                img = render.render_key(look, icons.get_icon(look["icon"], action, on_ready=self._icon_ready), 1)
                if self._send_img(x, y, img):
                    self._sent_keys[i] = sig
        if use_fx:
            style = {"wave": 0, "sweep": 1, "pop": 2}.get(self.cfg.get("fx_style", "wave"), 0)
            self.link.send_wait({"t": "show", "from": trans["from"], "style": style}, 3.0)
        # Leiste
        zones = self.cfg["bar"]["zones"]
        rects = render.zone_rects([z["w"] for z in zones])
        layout_sig = json.dumps(rects)
        if self._sent_zones.get("layout") != layout_sig:
            self._sent_zones.clear()
            self._zone_imgs.clear()
            self._send_img(render.BAR_X, render.BAR_Y, render.card_image(render.BAR_W, render.BAR_H, (0, 0, 0)))
            self._sent_zones["layout"] = layout_sig
        for zi, (z, (zx, zw)) in enumerate(zip(zones, rects)):
            x = render.BAR_X + zx
            if z["type"] == "gif" and z["opts"].get("path"):
                key = ("bar", z["opts"]["path"], zx, zw, z.get("bg"))
                wanted_anims[BAR_ANIM_SLOT] = key
                if self._sent_anims.get(BAR_ANIM_SLOT) != key:
                    try:
                        frames = icons.load_frames(z["opts"]["path"], zw, render.BAR_H, BAR_ANIM_BYTES)
                        mask = render.rounded_mask((zw, render.BAR_H), 10)
                        imgs = []
                        for fr, _ in frames:
                            base = render.card_image(zw, render.BAR_H, (0, 0, 0))
                            base.paste(fr.convert("RGB"), (0, 0), mask)
                            imgs.append(base)
                        if imgs:
                            self._send_anim(BAR_ANIM_SLOT, x, render.BAR_Y, zw, render.BAR_H, imgs,
                                            [ms for _, ms in frames])
                    except Exception as e:
                        log.warning("GIF fuer die Leiste nicht ladbar: %s", e)
                    self._sent_anims[BAR_ANIM_SLOT] = key
                    self._sent_zones[zi] = None
                continue
            sig = widgets.zone_signature(z, zw, self.ctx, now)
            if self._sent_zones.get(zi) != sig:
                img = widgets.render_zone(z, zw, self.ctx, now)
                old = self._zone_imgs.get(zi) if zi in self._sent_zones else None
                box = None
                if old is not None and old.size == img.size:
                    box = ImageChops.difference(old, img).getbbox()
                    if box is None:                      # nichts hat sich sichtbar geaendert
                        self._sent_zones[zi] = sig
                        continue
                # nur den geaenderten Ausschnitt schicken (z. B. Fortschrittsbalken statt ganzem Cover)
                part = img.crop(box) if box else img
                ox, oy = (box[0], box[1]) if box else (0, 0)
                if self._send_img(x + ox, render.BAR_Y + oy, part):
                    self._sent_zones[zi] = sig
                    self._zone_imgs[zi] = img
                else:
                    self._zone_imgs.pop(zi, None)
                    self._sent_zones.pop(zi, None)
        # nicht mehr benoetigte Animationen anhalten
        for slot in list(self._sent_anims):
            if slot not in wanted_anims:
                self.link.send({"t": "anim", "slot": slot, "stop": True})
                del self._sent_anims[slot]

    def _profiles(self):
        if not self.cfg.get("auto_profiles", True):
            return
        fg = foreground_exe()
        if not fg or fg == self._last_fg or fg in ("deck5x2.exe", "python.exe", "pythonw.exe"):
            return
        self._last_fg = fg
        match = next((p for p in self.cfg["pages"] if fg in p.get("apps", [])), None)
        if match and match["id"] != self.page_id:
            if self.profile_page is None:
                self.profile_from = self.page_id
            self.goto(match["id"], push=False, manual=False)
            self.profile_page = match["id"]
        elif not match and self.profile_page and self.page_id == self.profile_page:
            back = self.profile_from or self.cfg["pages"][0]["id"]
            self.profile_from = self.profile_page = None
            self.goto(back, push=False, manual=False)

    def _worker(self):
        last_stats = 0.0
        while True:
            playing = any(z["type"] == "nowplaying" for z in self.cfg["bar"]["zones"]) and self.ctx.media.state["playing"]
            self._wake.wait(0.2 if playing else 0.5)
            self._wake.clear()
            try:
                if time.time() - last_stats > 2:
                    self.ctx.system.update()
                    last_stats = time.time()
                self._profiles()
                self._refresh()
            except Exception:
                log.exception("Fehler beim Aktualisieren des Decks")
                time.sleep(1)

    # ------------------------------------------------------------------ Vorschau fuer die Oberflaeche
    def preview_page(self, pid: str):
        page = config.page_by_id(self.cfg, pid)
        return [render.data_url(self.key_image(page, i, scale=2)) for i in range(config.NUM_KEYS)]

    def preview_key(self, key: dict, toggled=False):
        k = config._key(key, config.blank_key())
        page = {"id": "__preview__", "keys": [k] + [config.blank_key()] * (config.NUM_KEYS - 1)}
        self.toggles[("__preview__", 0)] = bool(toggled)
        return render.data_url(self.key_image(page, 0, scale=2))

    def preview_bar(self, zones: list):
        zones = [z for z in (config._zone(z) for z in zones) if z] or self.cfg["bar"]["zones"]
        rects = render.zone_rects([z["w"] for z in zones])
        now = dt.datetime.now()
        return [{"x": zx, "w": zw, "img": render.data_url(widgets.render_zone(z, zw, self.ctx, now, scale=2))}
                for z, (zx, zw) in zip(zones, rects)]
