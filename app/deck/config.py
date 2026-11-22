"""Speichert und laedt die Einstellungen der Deck-App (JSON in %APPDATA%\\Deck5x2)."""
import copy
import json
import os
import sys
import uuid
from pathlib import Path

NUM_KEYS = 10
MAX_PAGES = 30
MAX_ZONES = 4

DEFAULT_COLORS = ["#3B82F6", "#E11D48", "#22C55E", "#F59E0B", "#8B5CF6",
                  "#06B6D4", "#F97316", "#EC4899", "#84CC16", "#EAB308"]

ACTION_TYPES = {"none", "program", "website", "hotkey", "media", "text", "page", "system", "multi"}
LIVE_TYPES = {"none", "clock", "date", "cpu", "ram", "counter", "stopwatch"}
ICON_KINDS = {"none", "auto", "glyph", "emoji", "file"}
ZONE_TYPES = {"clock", "weather", "nowplaying", "system", "text", "gif", "empty"}


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def blank_action():
    return {"type": "none", "value": ""}


def blank_key(i=0):
    return {
        "text": "", "color": "#1E293B", "text_color": "auto", "show_text": True,
        "icon": {"kind": "none", "value": ""}, "icon_mode": "icon",
        "action": blank_action(), "hold": blank_action(),
        "toggle": {"enabled": False, "text": "", "color": "#E11D48", "icon": {"kind": "none", "value": ""},
                   "action": blank_action()},
        "live": "none",
    }


def default_keys():
    keys = []
    for i in range(NUM_KEYS):
        k = blank_key(i)
        k["text"] = f"F{13 + i}"
        k["color"] = DEFAULT_COLORS[i]
        keys.append(k)
    for i, (t, v, g) in zip((7, 8, 9), (("Play", "play_pause", "E768"), ("Leiser", "volume_down", "E993"),
                                       ("Lauter", "volume_up", "E995"))):
        keys[i].update(text=t, color="#1E293B", action={"type": "media", "value": v},
                       icon={"kind": "glyph", "value": g})
    return keys


DEFAULT_CONFIG = {
    "version": 2,
    "pages": [{"id": "home", "name": "Hauptseite", "apps": [], "keys": default_keys()}],
    "bar": {"zones": [
        {"w": 0.62, "type": "clock", "opts": {"seconds": False, "date": True}, "bg": "#111827"},
        {"w": 0.38, "type": "nowplaying", "opts": {}, "bg": "#111827"},
    ]},
    "time_sync": True,
    "autostart": False,
    "sleep_min": 0,
    "brightness": 100,
    "auto_profiles": True,
    "swipe_pages": True,
    "fx": True,
    "fx_style": "wave",
    "cal_backup": None,
}


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    p = Path(base) / "Deck5x2"
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    return config_dir() / "config.json"


# ---------------------------------------------------------------------------- Pruefen / ergaenzen
def _color(c, fallback):
    if isinstance(c, str) and len(c) == 7 and c.startswith("#"):
        try:
            int(c[1:], 16)
            return c.upper()
        except ValueError:
            pass
    return fallback


def _action(a, allow_multi=True):
    if not isinstance(a, dict) or a.get("type") not in ACTION_TYPES:
        return blank_action()
    t = a["type"]
    if t == "multi":
        if not allow_multi:
            return blank_action()
        steps = []
        for s in a.get("value") if isinstance(a.get("value"), list) else []:
            if isinstance(s, dict) and s.get("type") == "delay":
                try:
                    steps.append({"type": "delay", "value": str(max(0, min(60000, int(float(s.get("value", 0))))))})
                except ValueError:
                    pass
            elif isinstance(s, dict) and s.get("type") in ACTION_TYPES - {"multi", "none"}:
                steps.append(_action(s, allow_multi=False))
        return {"type": "multi", "value": steps[:20]}
    return {"type": t, "value": str(a.get("value", ""))[:2000]}


def _icon(i):
    if not isinstance(i, dict) or i.get("kind") not in ICON_KINDS:
        return {"kind": "none", "value": ""}
    out = {"kind": i["kind"], "value": str(i.get("value", ""))[:500]}
    if i.get("color"):
        out["color"] = _color(i.get("color"), "#FFFFFF")
    return out


def _key(src, fallback):
    k = copy.deepcopy(fallback)
    if not isinstance(src, dict):
        return k
    if isinstance(src.get("text"), str):
        k["text"] = src["text"][:40]
    k["color"] = _color(src.get("color"), k["color"])
    tc = src.get("text_color")
    k["text_color"] = "auto" if tc == "auto" else _color(tc, "auto")
    if isinstance(src.get("show_text"), bool):
        k["show_text"] = src["show_text"]
    k["icon"] = _icon(src.get("icon"))
    if src.get("icon_mode") in ("icon", "full"):
        k["icon_mode"] = src["icon_mode"]
    k["action"] = _action(src.get("action"))
    k["hold"] = _action(src.get("hold"))
    tg = src.get("toggle") if isinstance(src.get("toggle"), dict) else {}
    k["toggle"] = {
        "enabled": bool(tg.get("enabled", False)),
        "text": str(tg.get("text", ""))[:40],
        "color": _color(tg.get("color"), "#E11D48"),
        "icon": _icon(tg.get("icon")),
        "action": _action(tg.get("action")),
    }
    if src.get("live") in LIVE_TYPES:
        k["live"] = src["live"]
    return k


def _zone(z):
    if not isinstance(z, dict) or z.get("type") not in ZONE_TYPES:
        return None
    try:
        w = max(0.08, min(1.0, float(z.get("w", 0.5))))
    except (TypeError, ValueError):
        w = 0.5
    opts = z.get("opts") if isinstance(z.get("opts"), dict) else {}
    clean = {}
    for k, v in opts.items():
        if isinstance(v, (str, bool, int, float)) or v is None:
            clean[str(k)[:30]] = v if not isinstance(v, str) else v[:500]
    return {"w": w, "type": z["type"], "opts": clean, "bg": _color(z.get("bg"), "#111827")}


def normalize(cfg: dict) -> dict:
    """Ergaenzt fehlende Felder, damit alte oder kaputte Dateien die App nicht stoppen.
    Alte Einstellungen (Version 1: nur 10 Tasten) werden uebernommen."""
    out = copy.deepcopy(DEFAULT_CONFIG)
    if not isinstance(cfg, dict):
        return out
    if cfg.get("fx_style") in ("wave", "sweep", "pop"):
        out["fx_style"] = cfg["fx_style"]
    for k in ("time_sync", "autostart", "auto_profiles", "swipe_pages", "fx"):
        if isinstance(cfg.get(k), bool):
            out[k] = cfg[k]
    for k, lo, hi in (("sleep_min", 0, 240), ("brightness", 5, 100)):
        try:
            out[k] = int(max(lo, min(hi, int(cfg.get(k, out[k])))))
        except (TypeError, ValueError):
            pass
    cb = cfg.get("cal_backup")
    if isinstance(cb, list) and len(cb) == 8 and all(isinstance(v, int) for v in cb):
        out["cal_backup"] = cb

    pages_src = cfg.get("pages")
    if not isinstance(pages_src, list) and isinstance(cfg.get("keys"), list):      # Version 1
        pages_src = [{"id": "home", "name": "Hauptseite", "keys": cfg["keys"]}]
    if isinstance(pages_src, list) and pages_src:
        pages, seen = [], set()
        for p in pages_src[:MAX_PAGES]:
            if not isinstance(p, dict):
                continue
            pid = str(p.get("id") or new_id())[:20]
            if pid in seen:
                pid = new_id()
            seen.add(pid)
            keys_src = p.get("keys") if isinstance(p.get("keys"), list) else []
            keys = []
            for i in range(NUM_KEYS):
                fb = blank_key(i)
                keys.append(_key(keys_src[i], fb) if i < len(keys_src) else fb)
            apps = [str(a).lower()[:80] for a in p.get("apps", []) if isinstance(a, str) and a.strip()][:10]
            pages.append({"id": pid, "name": str(p.get("name") or "Seite")[:30], "apps": apps, "keys": keys,
                          "inherit": bool(p.get("inherit", False))})
        if pages:
            pages[0]["id"] = pages[0]["id"] or "home"
            out["pages"] = pages

    bar = cfg.get("bar")
    if isinstance(bar, dict) and isinstance(bar.get("zones"), list):
        zones = [z for z in (_zone(z) for z in bar["zones"][:MAX_ZONES]) if z]
        if zones:
            out["bar"] = {"zones": zones}
    return out


def load() -> dict:
    try:
        with open(config_path(), encoding="utf-8") as f:
            return normalize(json.load(f))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULT_CONFIG)


def save(cfg: dict) -> dict:
    cfg = normalize(cfg)
    tmp = config_path().with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, config_path())
    return cfg


def is_blank(k: dict) -> bool:
    """Leere Taste: keine Beschriftung, kein Icon, keine Aktion."""
    return (not k["text"].strip() and k["icon"]["kind"] == "none" and k["action"]["type"] == "none"
            and k["hold"]["type"] == "none" and k["live"] == "none" and not k["toggle"]["enabled"])


def effective_key(cfg: dict, page: dict, i: int):
    """Taste, wie sie auf einer Seite wirkt: leere Tasten einer Seite mit 'inherit' kommen von der Hauptseite."""
    k = page["keys"][i]
    main = cfg["pages"][0]
    if page.get("inherit") and page is not main and page["id"] != main["id"] and is_blank(k):
        return main["keys"][i], main["id"]
    return k, page["id"]


def page_by_id(cfg: dict, pid: str):
    for p in cfg["pages"]:
        if p["id"] == pid:
            return p
    return cfg["pages"][0]


# ---------------------------------------------------------------------------- Fuer das Deck ohne App
_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})


def device_text(text: str) -> str:
    """Die eingebaute Schrift im Deck kennt keine Umlaute: ae/oe/ue/ss, nur ASCII, max. 23 Zeichen."""
    t = text.translate(_UMLAUTE)
    t = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in t)
    return t[:23]


def device_layout(cfg: dict) -> dict:
    """Beschriftung der Hauptseite: zeigt das Deck, wenn die App nicht laeuft (Tasten senden dann F13-F22)."""
    keys = cfg["pages"][0]["keys"]
    return {"t": "layout", "keys": [{"text": device_text(k["text"]) or f"F{13 + i}", "color": k["color"]}
                                    for i, k in enumerate(keys)]}


def resource_path(rel: str) -> Path:
    """Pfad zu mitgelieferten Dateien, auch in der fertigen .exe (PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel
