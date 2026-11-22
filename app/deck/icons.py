"""Icons fuer die Tasten: eigene Bilder, Symbole (Windows-Symbolschrift), Emoji oder automatisch
(Programm-Icon aus der .exe, Logo einer Webseite)."""
import hashlib
import io
import logging
import os
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageSequence

from . import render
from .config import config_dir

log = logging.getLogger("deck.icons")

# Auswahl aus der Symbolschrift von Windows (Segoe Fluent Icons / Segoe MDL2 Assets)
GLYPHS = [
    ("E768", "Play"), ("E769", "Pause"), ("E71A", "Stopp"), ("E892", "Zurück"), ("E893", "Weiter"),
    ("E767", "Lautstärke"), ("E74F", "Stumm"), ("E720", "Mikrofon"), ("EC54", "Mikro aus"), ("E7F6", "Kopfhörer"),
    ("E7F5", "Lautsprecher"), ("E8D6", "Musik"), ("E714", "Video"), ("E722", "Kamera"), ("E8B8", "Webcam"),
    ("E7C8", "Aufnahme"), ("E91B", "Foto"), ("E7FC", "Spiele"), ("E7F4", "Monitor"), ("E770", "PC"),
    ("E80F", "Start"), ("E713", "Einstellungen"), ("E721", "Suche"), ("E774", "Web"), ("E909", "Welt"),
    ("E715", "Mail"), ("E8BD", "Nachricht"), ("E717", "Telefon"), ("E716", "Personen"), ("E77B", "Kontakt"),
    ("E787", "Kalender"), ("E917", "Uhr"), ("E916", "Stoppuhr"), ("E8B7", "Ordner"), ("E8A5", "Dokument"),
    ("E8E5", "Datei öffnen"), ("E896", "Download"), ("E898", "Upload"), ("E753", "Cloud"), ("E72D", "Teilen"),
    ("E71B", "Link"), ("E8C8", "Kopieren"), ("E77F", "Einfügen"), ("E8C6", "Ausschneiden"), ("E7A7", "Rückgängig"),
    ("E7A6", "Wiederholen"), ("E74E", "Speichern"), ("E70F", "Bearbeiten"), ("E74D", "Löschen"), ("E710", "Plus"),
    ("E72C", "Neu laden"), ("E72E", "Schloss"), ("E785", "Offen"), ("E7E8", "Ein/Aus"), ("E708", "Mond"),
    ("E706", "Sonne"), ("E945", "Blitz"), ("E734", "Stern"), ("EB51", "Herz"), ("E7C1", "Flagge"),
    ("E718", "Pin"), ("E719", "Shop"), ("E765", "Tastatur"), ("E943", "Code"), ("EBE8", "Bug"),
    ("E8EF", "Rechner"), ("E701", "WLAN"), ("E702", "Bluetooth"), ("E709", "Flugzeug"), ("E707", "Ort"),
    ("E946", "Info"), ("E7BA", "Warnung"), ("E73E", "Haken"), ("E711", "Kreuz"), ("E72B", "Pfeil zurück"),
    ("E72A", "Pfeil vor"), ("E74A", "Hoch"), ("E74B", "Runter"), ("E890", "Auge"), ("E8FD", "Liste"),
    ("E76E", "Smiley"), ("EA86", "Puzzle"), ("E790", "Farbe"),
]

AUTO_GLYPH = {
    ("media", "play_pause"): "E768", ("media", "next"): "E893", ("media", "previous"): "E892",
    ("media", "volume_up"): "E995", ("media", "volume_down"): "E993", ("media", "mute"): "E74F",
    ("system", "lock"): "E72E", ("system", "taskmgr"): "E9D9", ("system", "desktop"): "E7F4",
    ("system", "explorer"): "E8B7", ("system", "screenshot"): "E722", ("system", "settings"): "E713",
    ("system", "calc"): "E8EF", ("system", "deck_sleep"): "E708", ("system", "emoji"): "E76E",
    ("system", "clipboard"): "E77F",
    ("hotkey", None): "E765", ("text", None): "E8D2", ("multi", None): "E8FD", ("page", None): "E8B7",
    ("page", "__back__"): "E72B", ("page", "__home__"): "E80F", ("page", "__next__"): "E72A",
    ("page", "__prev__"): "E72B", ("website", None): "E774", ("program", None): "E770",
}

_cache: dict = {}
_lock = threading.Lock()
_pending: set = set()


def icons_dir() -> Path:
    p = config_dir() / "icons"
    p.mkdir(exist_ok=True)
    return p


def cache_dir() -> Path:
    p = config_dir() / "cache"
    p.mkdir(exist_ok=True)
    return p


# ---------------------------------------------------------------------------- Symbole und Emoji
def glyph_image(code: str, color=(255, 255, 255), size=96) -> Image.Image | None:
    if not render.has_font("icons"):
        return None
    try:
        ch = chr(int(code, 16))
    except ValueError:
        return None
    f = render.font(size, "icons")
    img = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((size, size), ch, font=f, fill=color + (255,), anchor="mm")
    bb = img.getbbox()
    return img.crop(bb) if bb else None


def emoji_image(text: str, size=109) -> Image.Image | None:
    f = render.font(size, "emoji")
    img = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
    try:
        ImageDraw.Draw(img).text((size, size), text, font=f, embedded_color=True, anchor="mm")
    except Exception:
        ImageDraw.Draw(img).text((size, size), text, font=f, fill=(255, 255, 255, 255), anchor="mm")
    bb = img.getbbox()
    return img.crop(bb) if bb else None


# ---------------------------------------------------------------------------- Dateien
def import_image(path: str) -> str:
    """Kopiert ein gewaehltes Bild in den App-Ordner, damit es nicht verloren geht."""
    src = Path(path)
    data = src.read_bytes()
    name = hashlib.sha1(data).hexdigest()[:12] + src.suffix.lower()
    dst = icons_dir() / name
    if not dst.exists():
        dst.write_bytes(data)
    return str(dst)


def load_frames(path: str, w: int, h: int, max_bytes: int, fit="cover"):
    """GIF -> Liste von (Bild, ms). Zu viele Bilder werden ausgedünnt, damit sie ins Deck passen."""
    im = Image.open(path)
    frames = []
    for fr in ImageSequence.Iterator(im):
        ms = fr.info.get("duration", im.info.get("duration", 100)) or 100
        frames.append((fr.convert("RGBA"), max(20, int(ms))))
    if not frames:
        return []
    per = w * h * 2
    limit = max(1, max_bytes // per)
    if len(frames) > limit:
        step = len(frames) / limit
        picked = []
        for k in range(limit):
            a = int(k * step)
            b = int((k + 1) * step)
            picked.append((frames[a][0], sum(ms for _, ms in frames[a:b])))
        frames = picked
    out = []
    for img, ms in frames:
        if fit == "cover":
            img = render.cover(img, w, h)
        else:
            canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            img.thumbnail((w, h), Image.LANCZOS)
            canvas.alpha_composite(img, ((w - img.width) // 2, (h - img.height) // 2))
            img = canvas
        out.append((img, min(ms, 65000)))
    return out


def is_animated(path: str) -> bool:
    try:
        with Image.open(path) as im:
            return getattr(im, "is_animated", False) and im.n_frames > 1
    except Exception:
        return False


# ---------------------------------------------------------------------------- Automatisch
def _resolve_lnk(path: str) -> str:
    if sys.platform != "win32" or not path.lower().endswith(".lnk"):
        return path
    try:
        ps = f"(New-Object -ComObject WScript.Shell).CreateShortcut('{path.replace(chr(39), chr(39) * 2)}').TargetPath"
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                             text=True, timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        t = out.stdout.strip()
        return t or path
    except Exception:
        return path


def exe_icon(path: str) -> Image.Image | None:
    path = _resolve_lnk(path)
    if not path.lower().endswith(".exe") or not os.path.exists(path):
        return None
    key = hashlib.sha1(path.lower().encode()).hexdigest()[:16]
    cached = cache_dir() / f"exe_{key}.png"
    if cached.exists():
        return Image.open(cached).convert("RGBA")
    try:
        from icoextract import IconExtractor
        data = IconExtractor(path).get_icon()
        ico = Image.open(data)
        sizes = sorted(ico.info.get("sizes", [ico.size]), key=lambda s: s[0])
        try:
            ico.size = sizes[-1]
        except Exception:
            pass
        img = ico.convert("RGBA")
        img.save(cached)
        return img
    except Exception as e:
        log.info("Kein Icon aus %s: %s", path, e)
        return None


def favicon(url: str) -> Image.Image | None:
    host = urllib.parse.urlparse(url if "://" in url else "https://" + url).hostname
    if not host:
        return None
    cached = cache_dir() / f"fav_{host}.png"
    if cached.exists():
        try:
            return Image.open(cached).convert("RGBA")
        except Exception:
            pass
    for src in (f"https://www.google.com/s2/favicons?domain={host}&sz=128",
                f"https://icons.duckduckgo.com/ip3/{host}.ico"):
        try:
            req = urllib.request.Request(src, headers={"User-Agent": "Deck5x2"})
            with urllib.request.urlopen(req, timeout=6) as r:
                img = Image.open(io.BytesIO(r.read())).convert("RGBA")
            if img.width >= 16:
                img.save(cached)
                return img
        except Exception:
            continue
    return None


def auto_icon(action: dict) -> Image.Image | None:
    t = (action or {}).get("type", "none")
    v = str((action or {}).get("value", ""))
    if t == "program" and v:
        if os.path.isdir(v):
            return glyph_image("E8B7")
        img = exe_icon(v)
        if img:
            return img
    if t == "website" and v:
        img = favicon(v)
        if img:
            return img
    code = AUTO_GLYPH.get((t, v)) or AUTO_GLYPH.get((t, None))
    return glyph_image(code) if code else None


# ---------------------------------------------------------------------------- Einstieg
def get_icon(spec: dict, action: dict, on_ready=None) -> Image.Image | None:
    """Icon fuer eine Taste. Langsame Quellen (Internet, .exe) laden im Hintergrund;
    on_ready wird aufgerufen, sobald sie da sind."""
    kind = (spec or {}).get("kind", "none")
    value = str((spec or {}).get("value", ""))
    if kind == "none":
        return None
    color = render.hex_rgb(spec.get("color", "#FFFFFF"), (255, 255, 255))
    if kind == "glyph":
        key = ("glyph", value, color)
    elif kind == "emoji":
        key = ("emoji", value)
    elif kind == "file":
        try:
            key = ("file", value, os.path.getmtime(value))
        except OSError:
            return None
    elif kind == "auto":
        key = ("auto", action.get("type"), str(action.get("value", "")))
    else:
        return None
    with _lock:
        if key in _cache:
            return _cache[key]

    def load():
        if kind == "glyph":
            return glyph_image(value, color)
        if kind == "emoji":
            return emoji_image(value)
        if kind == "file":
            with Image.open(value) as im:
                im.seek(0)
                return im.convert("RGBA")
        return auto_icon(action)

    slow = kind == "auto" and action.get("type") in ("program", "website")
    if not slow:
        try:
            img = load()
        except Exception as e:
            log.info("Icon nicht ladbar (%s): %s", key, e)
            img = None
        with _lock:
            _cache[key] = img
        return img

    with _lock:
        if key in _pending:
            return None
        _pending.add(key)

    def worker():
        try:
            img = load()
        except Exception:
            img = None
        with _lock:
            _cache[key] = img
            _pending.discard(key)
        if on_ready:
            on_ready()

    threading.Thread(target=worker, daemon=True).start()
    return None
