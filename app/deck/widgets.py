"""Inhalte fuer die Leiste und Live-Tasten: Uhr, Wetter, laeuft gerade (Spotify & Co.), System, Text, GIF."""
import asyncio
import datetime as dt
import io
import json
import logging
import sys
import threading
import time
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw

from . import icons, render

log = logging.getLogger("deck.widgets")

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MUTED = (148, 163, 184)
WHITE = (255, 255, 255)
ACCENT = (60, 196, 211)

WIDGET_TYPES = ["clock", "weather", "nowplaying", "system", "text", "gif", "empty"]


# ---------------------------------------------------------------------------- System
class SystemStats:
    def __init__(self):
        self.cpu = 0.0
        self.ram = 0.0
        try:
            import psutil
            self._ps = psutil
            psutil.cpu_percent(None)
        except Exception:
            self._ps = None

    def update(self):
        if self._ps:
            self.cpu = self._ps.cpu_percent(None)
            self.ram = self._ps.virtual_memory().percent


# ---------------------------------------------------------------------------- Wetter (Open-Meteo, ohne Anmeldung)
WMO = {
    0: "Klar", 1: "Überwiegend klar", 2: "Teils bewölkt", 3: "Bewölkt", 45: "Nebel", 48: "Reifnebel",
    51: "Leichter Niesel", 53: "Niesel", 55: "Starker Niesel", 56: "Gefrierender Niesel", 57: "Gefrierender Niesel",
    61: "Leichter Regen", 63: "Regen", 65: "Starker Regen", 66: "Eisregen", 67: "Eisregen",
    71: "Leichter Schnee", 73: "Schnee", 75: "Starker Schnee", 77: "Schneegriesel",
    80: "Regenschauer", 81: "Regenschauer", 82: "Heftige Schauer", 85: "Schneeschauer", 86: "Schneeschauer",
    95: "Gewitter", 96: "Gewitter mit Hagel", 99: "Gewitter mit Hagel",
}


def _get_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "Deck5x2"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def geocode(name: str):
    q = urllib.parse.urlencode({"name": name, "count": 6, "language": "de", "format": "json"})
    data = _get_json(f"https://geocoding-api.open-meteo.com/v1/search?{q}")
    out = []
    for r in data.get("results") or []:
        label = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country")) if x)
        out.append({"name": r.get("name"), "label": label, "lat": r.get("latitude"), "lon": r.get("longitude")})
    return out


class Weather:
    """Laedt das Wetter fuer einen Ort alle 15 Minuten."""

    def __init__(self):
        self.data = {}           # (lat, lon) -> dict
        self._busy = set()

    def get(self, lat, lon):
        if lat is None or lon is None:
            return None
        key = (round(float(lat), 3), round(float(lon), 3))
        d = self.data.get(key)
        if (d is None or time.time() - d["at"] > 900) and key not in self._busy:
            self._busy.add(key)
            threading.Thread(target=self._load, args=(key,), daemon=True).start()
        return d

    def _load(self, key):
        try:
            q = urllib.parse.urlencode({
                "latitude": key[0], "longitude": key[1], "timezone": "auto",
                "current": "temperature_2m,weather_code,is_day,apparent_temperature",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max", "forecast_days": 1})
            j = _get_json(f"https://api.open-meteo.com/v1/forecast?{q}")
            c, d = j.get("current", {}), j.get("daily", {})
            self.data[key] = {
                "at": time.time(), "temp": c.get("temperature_2m"), "code": c.get("weather_code", 0),
                "day": bool(c.get("is_day", 1)), "feels": c.get("apparent_temperature"),
                "max": (d.get("temperature_2m_max") or [None])[0], "min": (d.get("temperature_2m_min") or [None])[0],
                "rain": (d.get("precipitation_probability_max") or [None])[0]}
        except Exception as e:
            log.info("Wetter nicht geladen: %s", e)
            old = self.data.get(key)
            if old:
                old["at"] = time.time() - 600          # in 5 Minuten noch mal versuchen
        finally:
            self._busy.discard(key)


def draw_weather_icon(size: int, code: int, day: bool = True) -> Image.Image:
    """Einfache Wetter-Symbole, selbst gezeichnet (keine Schrift noetig)."""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    sun, moon, cloud, dark = (251, 191, 36), (226, 232, 240), (226, 232, 240), (148, 163, 184)
    rain, snow, bolt = (96, 165, 250), (255, 255, 255), (250, 204, 21)

    def sun_at(cx, cy, r):
        if day:
            import math
            for k in range(8):
                a = k * math.pi / 4
                d.line((cx + math.cos(a) * r * 1.35, cy + math.sin(a) * r * 1.35,
                        cx + math.cos(a) * r * 1.75, cy + math.sin(a) * r * 1.75), fill=sun, width=max(2, s // 28))
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=sun)
        else:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=moon)
            d.ellipse((cx - r * 0.35, cy - r * 1.15, cx + r * 1.4, cy + r * 0.6), fill=(0, 0, 0, 0))

    def cloud_at(cx, cy, w, col):
        h = w * 0.5
        d.ellipse((cx - w * 0.5, cy - h * 0.1, cx - w * 0.05, cy + h * 0.55), fill=col)
        d.ellipse((cx - w * 0.3, cy - h * 0.65, cx + w * 0.2, cy + h * 0.4), fill=col)
        d.ellipse((cx + w * 0.0, cy - h * 0.35, cx + w * 0.5, cy + h * 0.55), fill=col)
        d.rounded_rectangle((cx - w * 0.5 + h * 0.3, cy, cx + w * 0.5 - h * 0.25, cy + h * 0.55), h * 0.25, fill=col)

    c = int(code or 0)
    if c == 0:
        sun_at(s / 2, s / 2, s * 0.22)
    elif c in (1, 2):
        sun_at(s * 0.38, s * 0.36, s * 0.17)
        cloud_at(s * 0.56, s * 0.58, s * 0.62, cloud)
    elif c in (3, 45, 48):
        cloud_at(s * 0.5, s * 0.5, s * 0.78, dark if c == 3 else cloud)
        if c in (45, 48):
            for k in range(3):
                y = s * (0.72 + k * 0.08)
                d.line((s * 0.18, y, s * 0.82, y), fill=dark, width=s // 24)
    else:
        cloud_at(s * 0.5, s * 0.4, s * 0.74, dark)
        if c in (71, 73, 75, 77, 85, 86):
            for k in range(3):
                x = s * (0.32 + k * 0.18)
                d.ellipse((x - s * 0.035, s * 0.78 - s * 0.035, x + s * 0.035, s * 0.78 + s * 0.035), fill=snow)
        elif c >= 95:
            d.polygon([(s * 0.52, s * 0.6), (s * 0.4, s * 0.8), (s * 0.5, s * 0.8), (s * 0.44, s * 0.97),
                       (s * 0.64, s * 0.72), (s * 0.53, s * 0.72), (s * 0.6, s * 0.6)], fill=bolt)
        else:
            for k in range(3):
                x = s * (0.33 + k * 0.17)
                d.line((x, s * 0.68, x - s * 0.05, s * 0.86), fill=rain, width=s // 22)
    return img.resize((size, size), Image.LANCZOS)


# ---------------------------------------------------------------------------- Laeuft gerade
class NowPlaying:
    """Fragt bei Windows nach, was gerade abgespielt wird (Spotify, Browser, ...)."""

    def __init__(self):
        self.state = {"title": "", "artist": "", "playing": False, "pos": 0.0, "dur": 0.0, "cover": None,
                      "at": 0.0, "app": ""}
        self._cover_key = None
        self._wanted = False
        self._thread = None
        self._ok = sys.platform == "win32"

    def want(self):
        """Erst abfragen, wenn ein Widget es braucht."""
        self._wanted = True
        if self._ok and not self._thread:
            self._thread = threading.Thread(target=self._run, daemon=True, name="nowplaying")
            self._thread.start()

    def position(self):
        st = self.state
        if st["playing"] and st["dur"]:
            return min(st["dur"], st["pos"] + (time.time() - st["at"]))
        return st["pos"]

    def _run(self):
        try:
            from winrt.windows.media.control import \
                GlobalSystemMediaTransportControlsSessionManager as Manager
        except Exception as e:
            log.info("Windows-Medienabfrage nicht verfuegbar (%s), nutze Spotify-Fenstertitel", e)
            Manager = None
        loop = asyncio.new_event_loop()
        while True:
            try:
                if Manager:
                    loop.run_until_complete(self._poll(Manager))
                else:
                    self._poll_title()
            except Exception as e:
                log.debug("Medienabfrage: %s", e)
            time.sleep(1.0)

    async def _poll(self, Manager):
        mgr = await Manager.request_async()
        s = mgr.get_current_session()
        if s is None:
            self.state.update(title="", artist="", playing=False, cover=None, pos=0.0, dur=0.0, at=time.time())
            return
        props = await s.try_get_media_properties_async()
        info = s.get_playback_info()
        tl = s.get_timeline_properties()
        title = props.title if props else ""
        artist = props.artist if props else ""
        playing = int(info.playback_status) == 4 if info else False
        try:
            pos = tl.position.total_seconds()
            dur = tl.end_time.total_seconds()
            upd = tl.last_updated_time
            age = (dt.datetime.now(dt.timezone.utc) - upd).total_seconds() if upd and playing else 0
            if 0 < age < 3600:
                pos += age
        except Exception:
            pos = dur = 0.0
        cover = self.state["cover"]
        key = (title, artist)
        if key != self._cover_key:
            cover = None
            self._cover_key = key
            try:
                if props and props.thumbnail:
                    from winrt.windows.storage.streams import Buffer, InputStreamOptions
                    stream = await props.thumbnail.open_read_async()
                    buf = Buffer(int(stream.size))
                    buf = await stream.read_async(buf, buf.capacity, InputStreamOptions.READ_AHEAD)
                    cover = Image.open(io.BytesIO(bytes(buf))).convert("RGB")
            except Exception as e:
                log.debug("Kein Cover: %s", e)
        self.state.update(title=_clean(title), artist=_clean(artist), playing=playing, pos=pos, dur=dur,
                          cover=cover, at=time.time(), app=s.source_app_user_model_id or "")

    def _poll_title(self):
        """Notloesung: Titel aus dem Spotify-Fenster ('Kuenstler - Titel')."""
        if sys.platform != "win32":
            return
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            n = user32.GetWindowTextLengthW(hwnd)
            if n and user32.IsWindowVisible(hwnd):
                b = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, b, n + 1)
                cls = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(hwnd, cls, 64)
                if cls.value == "Chrome_WidgetWin_0" and " - " in b.value:
                    found.append(b.value)
            return True

        user32.EnumWindows(cb, 0)
        if found:
            artist, _, title = found[0].partition(" - ")
            self.state.update(title=title, artist=artist, playing=True, at=time.time())
        else:
            self.state.update(title="", artist="", playing=False)


# ---------------------------------------------------------------------------- Zeichnen der Bereiche
def _clean(text: str) -> str:
    """Emoji und Sonderzeichen entfernen, die die Schrift nicht kennt (sonst erscheinen Kaestchen)."""
    out = []
    for ch in text or "":
        o = ord(ch)
        if o >= 0x1F000 or 0x2600 <= o <= 0x27BF or 0xFE00 <= o <= 0xFE0F or o == 0x200D or 0xE000 <= o <= 0xF8FF:
            continue
        out.append(ch)
    return " ".join("".join(out).split())


def _fmt_time(sec):
    sec = int(max(0, sec))
    return f"{sec // 60}:{sec % 60:02d}"


class Context:
    """Alles, was Widgets zum Zeichnen brauchen."""

    def __init__(self):
        self.system = SystemStats()
        self.weather = Weather()
        self.media = NowPlaying()


def zone_signature(zone: dict, w: int, ctx: Context, now: dt.datetime):
    t = zone.get("type", "empty")
    o = zone.get("opts", {})
    base = (t, w, json.dumps(o, sort_keys=True), zone.get("bg"))
    if t == "clock":
        return base + (now.strftime("%H:%M:%S" if o.get("seconds") else "%H:%M %d"),)
    if t == "weather":
        d = ctx.weather.get(o.get("lat"), o.get("lon"))
        return base + ((d or {}).get("temp"), (d or {}).get("code"), (d or {}).get("max"), (d or {}).get("min"))
    if t == "nowplaying":
        ctx.media.want()
        st = ctx.media.state
        prog = int(ctx.media.position() / max(1, st["dur"]) * (w // 4)) if st["dur"] else 0
        return base + (st["title"], st["artist"], st["playing"], prog, id(st["cover"]),
                       _fmt_time(ctx.media.position()) if w >= 260 else "")
    if t == "system":
        return base + (round(ctx.system.cpu), round(ctx.system.ram))
    return base


def render_zone(zone: dict, w: int, ctx: Context, now: dt.datetime | None = None, scale: int = 1) -> Image.Image:
    h = render.BAR_H
    now = now or dt.datetime.now()
    t = zone.get("type", "empty")
    o = zone.get("opts", {})
    bg = render.hex_rgb(zone.get("bg") or "#111827")
    img = render.card_image(w, h, bg, scale)
    S = scale
    d = ImageDraw.Draw(img)
    fg = render.auto_text_color(bg)
    muted = MUTED if fg == WHITE else (71, 85, 105)
    pw, ph = w * S, h * S

    if t == "clock":
        hhmm = now.strftime("%H:%M")
        sec = now.strftime(":%S") if o.get("seconds") else ""
        date = now.strftime("%d.%m.%Y")
        wd = WOCHENTAGE[now.weekday()]
        show_date = o.get("date", True)
        if w >= 300 and show_date:
            big = render.font(int(58 * S), "semibold")
            d.text((20 * S, ph / 2), hhmm, font=big, fill=fg, anchor="lm")
            if sec:
                bw = d.textlength(hhmm, font=big)
                d.text((20 * S + bw + 2 * S, ph / 2 + 14 * S), sec, font=render.font(int(24 * S), "semibold"), fill=muted, anchor="ls")
            f2 = render.font(int(19 * S), "regular")
            d.text((pw - 20 * S, ph / 2 - 13 * S), wd, font=f2, fill=muted, anchor="rm")
            d.text((pw - 20 * S, ph / 2 + 15 * S), date, font=f2, fill=muted, anchor="rm")
        else:
            txt = hhmm + sec
            for size in (60, 54, 48, 42, 36, 30, 26, 22):
                big = render.font(int(size * S), "semibold")
                if d.textlength(txt, font=big) <= pw - 16 * S:
                    break
            cy = ph / 2 - (12 * S if show_date else 0)
            d.text((pw / 2, cy), txt, font=big, fill=fg, anchor="mm")
            if show_date:
                small = f"{wd[:2]}, {now.strftime('%d.%m.')}" if w < 170 else f"{wd}, {now.strftime('%d.%m.')}"
                d.text((pw / 2, cy + size * S * 0.55 + 8 * S), small, font=render.font(int(16 * S), "regular"), fill=muted, anchor="mm")

    elif t == "weather":
        data = ctx.weather.get(o.get("lat"), o.get("lon"))
        name = o.get("name") or "Ort wählen"
        if not data:
            nf, sf = render.font(int(17 * S), "semibold"), render.font(int(13 * S), "regular")
            sub = "Wetter wird geladen …" if o.get("lat") is not None else "Ort in der App suchen"
            d.text((pw / 2, ph / 2 - 10 * S), render.ellipsize(d, name, nf, pw - 16 * S), font=nf, fill=fg, anchor="mm")
            d.text((pw / 2, ph / 2 + 14 * S), render.ellipsize(d, sub, sf, pw - 16 * S), font=sf, fill=muted, anchor="mm")
        else:
            temp = f"{round(data['temp'])}°" if data.get("temp") is not None else "–"
            ic = draw_weather_icon(int(64 * S), data.get("code", 0), data.get("day", True))
            desc = WMO.get(int(data.get("code") or 0), "")
            mm = ""
            if data.get("max") is not None:
                mm = f"{round(data['max'])}° / {round(data['min'])}°"
            if w >= 250:
                img.paste(ic, (int(14 * S), int((ph - ic.height) / 2)), ic)
                x = 14 * S + ic.width + 10 * S
                d.text((x, ph / 2 - 4 * S), temp, font=render.font(int(44 * S), "semibold"), fill=fg, anchor="ls")
                d.text((x, ph / 2 + 18 * S), desc, font=render.font(int(15 * S), "regular"), fill=muted, anchor="ls")
                d.text((x, ph / 2 + 38 * S), name, font=render.font(int(13 * S), "regular"), fill=muted, anchor="ls")
                if mm and w >= 330:
                    d.text((pw - 16 * S, 22 * S), mm, font=render.font(int(14 * S), "regular"), fill=muted, anchor="rm")
            else:
                ic = draw_weather_icon(int(46 * S), data.get("code", 0), data.get("day", True))
                img.paste(ic, (int((pw - ic.width) / 2), int(8 * S)), ic)
                d.text((pw / 2, 72 * S), temp, font=render.font(int(28 * S), "semibold"), fill=fg, anchor="mm")
                d.text((pw / 2, 96 * S), name if w >= 110 else name[:8], font=render.font(int(12 * S), "regular"), fill=muted, anchor="mm")

    elif t == "nowplaying":
        st = ctx.media.state
        if not st["title"]:
            d.text((pw / 2, ph / 2 - 9 * S), "Gerade läuft nichts", font=render.font(int(16 * S), "semibold"), fill=fg, anchor="mm")
            d.text((pw / 2, ph / 2 + 14 * S), "Tippen = Play / Pause", font=render.font(int(12 * S), "regular"), fill=muted, anchor="mm")
        else:
            pad = 12 * S
            x0 = pad
            cs = ph - 2 * pad
            if w >= 200:
                cov = st["cover"]
                if cov is not None:
                    c = render.cover(cov, cs, cs).convert("RGB")
                    img.paste(c, (int(pad), int(pad)), render.rounded_mask((cs, cs), 8 * S))
                else:
                    d.rounded_rectangle((pad, pad, pad + cs, pad + cs), 8 * S, fill=render.darker(bg, 1.6) if sum(bg) < 200 else render.darker(bg))
                    note = icons.glyph_image("E8D6", (148, 163, 184), int(cs * 0.45))
                    if note:
                        img.paste(note, (int(pad + (cs - note.width) / 2), int(pad + (cs - note.height) / 2)), note)
                x0 = pad + cs + 12 * S
            maxw = pw - x0 - pad
            tf = render.font(int((19 if w >= 260 else 16) * S), "semibold")
            af = render.font(int((15 if w >= 260 else 13) * S), "regular")
            d.text((x0, 30 * S), render.ellipsize(d, st["title"], tf, maxw), font=tf, fill=fg, anchor="lm")
            d.text((x0, 54 * S), render.ellipsize(d, st["artist"], af, maxw), font=af, fill=muted, anchor="lm")
            # Fortschritt
            by = ph - 26 * S
            d.rounded_rectangle((x0, by, pw - pad, by + 4 * S), 2 * S, fill=render.darker(muted, 0.5))
            if st["dur"]:
                f = min(1, ctx.media.position() / st["dur"])
                d.rounded_rectangle((x0, by, x0 + (pw - pad - x0) * f, by + 4 * S), 2 * S, fill=ACCENT)
                if w >= 260:
                    tf2 = render.font(int(11 * S), "regular")
                    d.text((x0, by + 16 * S), _fmt_time(ctx.media.position()), font=tf2, fill=muted, anchor="lm")
                    d.text((pw - pad, by + 16 * S), _fmt_time(st["dur"]), font=tf2, fill=muted, anchor="rm")
            if not st["playing"]:
                d.text((pw - pad, 30 * S), "❚❚", font=render.font(int(12 * S), "bold"), fill=muted, anchor="rm")

    elif t == "system":
        rows = [("CPU", ctx.system.cpu), ("RAM", ctx.system.ram)]
        lf = render.font(int(14 * S), "semibold")
        vf = render.font(int(14 * S), "regular")
        for k, (lab, val) in enumerate(rows):
            y = ph * (0.33 + 0.36 * k)
            d.text((16 * S, y - 10 * S), lab, font=lf, fill=muted, anchor="lm")
            d.text((pw - 16 * S, y - 10 * S), f"{round(val)} %", font=vf, fill=fg, anchor="rm")
            d.rounded_rectangle((16 * S, y + 4 * S, pw - 16 * S, y + 10 * S), 3 * S, fill=render.darker(muted, 0.45))
            col = (74, 222, 128) if val < 60 else (250, 204, 21) if val < 85 else (248, 113, 113)
            d.rounded_rectangle((16 * S, y + 4 * S, 16 * S + (pw - 32 * S) * min(1, val / 100), y + 10 * S), 3 * S, fill=col)

    elif t == "text":
        txt = o.get("text") or "Dein Text"
        col = render.hex_rgb(o.get("color") or "#FFFFFF", WHITE)
        lines, f = render.fit_lines(d, txt, pw - 24 * S, 3, [int(s * S) for s in (40, 34, 30, 26, 22, 19, 16, 14, 12)],
                                    "semibold")
        render.draw_lines(d, lines, f, pw / 2, ph / 2, col)

    elif t == "gif":
        path = o.get("path")
        if path:
            try:
                with Image.open(path) as im:
                    im.seek(0)
                    fr = render.cover(im.convert("RGBA"), pw, ph).convert("RGB")
                img.paste(fr, (0, 0), render.rounded_mask((pw, ph), 10 * S))
            except Exception:
                d.text((pw / 2, ph / 2), "GIF nicht gefunden", font=render.font(int(14 * S), "regular"), fill=muted, anchor="mm")
        else:
            d.text((pw / 2, ph / 2), "GIF auswählen", font=render.font(int(15 * S), "regular"), fill=muted, anchor="mm")
    return img


# ---------------------------------------------------------------------------- Live-Tasten
def live_text(kind: str, ctx: Context, state: dict, now: dt.datetime):
    if kind == "clock":
        return now.strftime("%H:%M")
    if kind == "date":
        return f"{WOCHENTAGE[now.weekday()][:2]} {now.strftime('%d.%m.')}"
    if kind == "cpu":
        return f"CPU {round(ctx.system.cpu)} %"
    if kind == "ram":
        return f"RAM {round(ctx.system.ram)} %"
    if kind == "counter":
        return str(state.get("count", 0))
    if kind == "stopwatch":
        sec = state.get("elapsed", 0.0) + (time.time() - state["started"] if state.get("started") else 0)
        sec = int(sec)
        return f"{sec // 3600}:{sec // 60 % 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60:02d}:{sec % 60:02d}"
    return None
