"""Speichert und laedt die Einstellungen der Deck-App (JSON in %APPDATA%\\Deck5x2)."""
import copy
import json
import os
import sys
from pathlib import Path

NUM_KEYS = 10

DEFAULT_COLORS = ["#3B82F6", "#E11D48", "#22C55E", "#F59E0B", "#8B5CF6",
                  "#06B6D4", "#F97316", "#EC4899", "#84CC16", "#EAB308"]

DEFAULT_CONFIG = {
    "version": 1,
    "keys": [
        {"text": f"F{13 + i}", "color": DEFAULT_COLORS[i], "action": {"type": "none", "value": ""}}
        for i in range(NUM_KEYS)
    ],
    "time_sync": True,
    "autostart": False,
}
# Beispielbelegung fuer die drei letzten Tasten
DEFAULT_CONFIG["keys"][7] = {"text": "Play", "color": "#1E293B", "action": {"type": "media", "value": "play_pause"}}
DEFAULT_CONFIG["keys"][8] = {"text": "Leiser", "color": "#1E293B", "action": {"type": "media", "value": "volume_down"}}
DEFAULT_CONFIG["keys"][9] = {"text": "Lauter", "color": "#1E293B", "action": {"type": "media", "value": "volume_up"}}

ACTION_TYPES = {"none", "program", "website", "hotkey", "media", "text"}


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    p = Path(base) / "Deck5x2"
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    return config_dir() / "config.json"


def normalize(cfg: dict) -> dict:
    """Ergaenzt fehlende Felder, damit alte oder kaputte Dateien die App nicht stoppen."""
    out = copy.deepcopy(DEFAULT_CONFIG)
    if not isinstance(cfg, dict):
        return out
    for k in ("time_sync", "autostart"):
        if isinstance(cfg.get(k), bool):
            out[k] = cfg[k]
    keys = cfg.get("keys")
    if isinstance(keys, list):
        for i in range(min(NUM_KEYS, len(keys))):
            src = keys[i] if isinstance(keys[i], dict) else {}
            dst = out["keys"][i]
            if isinstance(src.get("text"), str):
                dst["text"] = src["text"][:40]
            c = src.get("color")
            if isinstance(c, str) and len(c) == 7 and c.startswith("#"):
                try:
                    int(c[1:], 16)
                    dst["color"] = c.upper()
                except ValueError:
                    pass
            a = src.get("action")
            if isinstance(a, dict) and a.get("type") in ACTION_TYPES:
                dst["action"] = {"type": a["type"], "value": str(a.get("value", ""))}
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


_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})


def device_text(text: str) -> str:
    """Die Schrift im Deck kennt keine Umlaute: ae/oe/ue/ss, nur ASCII, max. 23 Zeichen."""
    t = text.translate(_UMLAUTE)
    t = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in t)
    return t[:23]


def device_layout(cfg: dict) -> dict:
    return {"t": "layout", "keys": [{"text": device_text(k["text"]), "color": k["color"]} for k in cfg["keys"]]}


def resource_path(rel: str) -> Path:
    """Pfad zu mitgelieferten Dateien, auch in der fertigen .exe (PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel
