"""Zeichnet Tasten und Leiste als Bilder (Pillow) und wandelt sie in das Format des Decks.

Das Deck bekommt fertige Bilder: so gehen Umlaute, Icons, schoene Schrift und Widgets,
ohne dass die Firmware etwas davon wissen muss.
"""
import base64
import io
import sys
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

# Bildschirm-Geometrie (muss zur Firmware passen)
W, H = 480, 320
KEY = 76
KX = [48, 144, 240, 336, 432]
KY = [48, 144]
BAR_X, BAR_Y, BAR_W, BAR_H = 9, 201, 462, 110
BAR_GAP = 6
KEY_RADIUS = 12


def key_origin(i: int):
    return KX[i % 5] - KEY // 2, KY[i // 5] - KEY // 2


# ---------------------------------------------------------------------------- Schriften
_FONT_FILES = {
    "bold": ["segoeuib.ttf", "seguisb.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "arialbd.ttf"],
    "semibold": ["seguisb.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf"],
    "regular": ["segoeui.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf", "arial.ttf"],
    "light": ["segoeuil.ttf", "segoeui.ttf", "DejaVuSans.ttf", "arial.ttf"],
    "icons": ["SegoeIcons.ttf", "segmdl2.ttf"],
    "emoji": ["seguiemj.ttf", "NotoColorEmoji.ttf"],
}
_LINUX_DIRS = ["/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/truetype/liberation/"]


@lru_cache(maxsize=256)
def font(size: int, weight: str = "bold"):
    for name in _FONT_FILES.get(weight, _FONT_FILES["regular"]):
        for cand in [name] + [d + name for d in _LINUX_DIRS]:
            try:
                return ImageFont.truetype(cand, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def has_font(weight: str) -> bool:
    for name in _FONT_FILES.get(weight, []):
        try:
            ImageFont.truetype(name, 10)
            return True
        except OSError:
            pass
    return False


# ---------------------------------------------------------------------------- Farben
def hex_rgb(c: str, fallback=(30, 41, 59)):
    try:
        c = c.lstrip("#")
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except (ValueError, IndexError, AttributeError):
        return fallback


def luminance(rgb) -> float:
    r, g, b = (v / 255 for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def auto_text_color(bg) -> tuple:
    return (17, 24, 39) if luminance(bg) > 0.62 else (255, 255, 255)


def darker(rgb, f=0.75):
    return tuple(int(v * f) for v in rgb)


# ---------------------------------------------------------------------------- Text
def text_size(draw, text, f):
    l, t, r, b = draw.textbbox((0, 0), text, font=f)
    return r - l, b - t


def fit_lines(draw, text: str, max_w: int, max_lines: int, sizes, weight="bold"):
    """Sucht die groesste Schrift, bei der der Text in max_lines Zeilen passt (Woerter werden nicht zerrissen)."""
    words = text.split()
    if not words:
        return [], font(sizes[0], weight)
    for s in sizes:
        f = font(s, weight)
        lines, cur = [], ""
        ok = True
        for w in words:
            cand = (cur + " " + w).strip()
            if text_size(draw, cand, f)[0] <= max_w:
                cur = cand
            else:
                if cur:
                    lines.append(cur)
                cur = w
                if text_size(draw, w, f)[0] > max_w:
                    ok = False
                    break
        if cur:
            lines.append(cur)
        if ok and len(lines) <= max_lines:
            return lines, f
    # passt nicht: kleinste Schrift, notfalls abschneiden
    f = font(sizes[-1], weight)
    out = []
    for w in words:
        while text_size(draw, w, f)[0] > max_w and len(w) > 1:
            w = w[:-1]
        out.append(w)
    return out[:max_lines], f


def ellipsize(draw, text: str, f, max_w: int) -> str:
    """Text kuerzen und mit … enden lassen, falls er nicht passt."""
    if draw.textlength(text, font=f) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=f) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def draw_lines(draw, lines, f, cx, cy, fill, spacing=1.08):
    if not lines:
        return
    asc, desc = f.getmetrics()
    lh = int((asc + desc) * spacing)
    total = lh * len(lines)
    y = cy - total / 2
    for ln in lines:
        draw.text((cx, y + lh / 2), ln, font=f, fill=fill, anchor="mm")
        y += lh


# ---------------------------------------------------------------------------- Tasten
def rounded_mask(size, radius, scale=1):
    w, h = size
    m = Image.new("L", (w * 4, h * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * 4 - 1, h * 4 - 1), radius * 4, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def fit_icon(icon: Image.Image, box: int) -> Image.Image:
    icon = icon.convert("RGBA")
    icon.thumbnail((box, box), Image.LANCZOS)
    if max(icon.size) < box * 0.7:                     # kleine Icons (Favicons) etwas groesser ziehen
        f = box / max(icon.size)
        icon = icon.resize((max(1, int(icon.width * f)), max(1, int(icon.height * f))), Image.LANCZOS)
    return icon


def cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Bild so skalieren und zuschneiden, dass es die Flaeche fuellt."""
    img = img.convert("RGBA")
    f = max(w / img.width, h / img.height)
    img = img.resize((max(1, round(img.width * f)), max(1, round(img.height * f))), Image.LANCZOS)
    l = (img.width - w) // 2
    t = (img.height - h) // 2
    return img.crop((l, t, l + w, t + h))


def render_key(look: dict, icon: Image.Image | None = None, scale: int = 1) -> Image.Image:
    """Eine Taste (76 x 76) als Bild.

    look: color, text, text_color ("auto" oder #RRGGBB), show_text, icon_mode ("icon" | "full")
    icon: fertiges Bild (RGBA) oder None
    """
    s = KEY * scale
    bg = hex_rgb(look.get("color", "#1E293B"))
    tc = auto_text_color(bg) if look.get("text_color", "auto") == "auto" else hex_rgb(look["text_color"], (255, 255, 255))
    text = (look.get("text") or "").strip() if look.get("show_text", True) else ""
    mode = look.get("icon_mode", "icon")

    out = Image.new("RGB", (s, s), (0, 0, 0))
    card = Image.new("RGBA", (s, s), bg + (255,))
    d = ImageDraw.Draw(card)
    pad = 6 * scale

    if icon is not None and mode == "full":
        card = cover(icon, s, s)
        if text:
            # dunkler Verlauf unten, damit der Text lesbar bleibt
            grad = Image.new("L", (1, s), 0)
            for y in range(s):
                grad.putpixel((0, y), int(max(0, (y - s * 0.45) / (s * 0.55)) * 190))
            shade = Image.new("RGBA", (s, s), (0, 0, 0, 255))
            shade.putalpha(grad.resize((s, s)))
            card = Image.alpha_composite(card, shade)
            d = ImageDraw.Draw(card)
            lines, f = fit_lines(d, text, s - 2 * pad, 1, [x * scale for x in (13, 12, 11, 10)])
            draw_lines(d, lines, f, s / 2, s - 13 * scale, (255, 255, 255))
    elif icon is not None:
        if text:
            box = 40 * scale
            ic = fit_icon(icon, box)
            card.alpha_composite(ic, ((s - ic.width) // 2, 8 * scale + (box - ic.height) // 2))
            lines, f = fit_lines(d, text, s - 2 * pad, 1, [x * scale for x in (13, 12, 11, 10, 9)])
            draw_lines(d, lines, f, s / 2, s - 14 * scale, tc)
        else:
            box = 54 * scale
            ic = fit_icon(icon, box)
            card.alpha_composite(ic, ((s - ic.width) // 2, (s - ic.height) // 2))
    elif text:
        lines, f = fit_lines(d, text, s - 2 * pad, 3, [x * scale for x in (17, 16, 15, 14, 13, 12, 11, 10)])
        draw_lines(d, lines, f, s / 2, s / 2, tc)

    out.paste(card.convert("RGB"), (0, 0), rounded_mask((s, s), KEY_RADIUS * scale))
    return out


# ---------------------------------------------------------------------------- Leiste
def zone_rects(widths, total=BAR_W, gap=BAR_GAP):
    """Breiten-Anteile -> (x, w) je Bereich innerhalb der Leiste."""
    n = max(1, len(widths))
    avail = total - gap * (n - 1)
    s = sum(widths) or 1
    xs, x = [], 0
    for i, f in enumerate(widths):
        w = round(avail * f / s) if i < n - 1 else total - x
        xs.append((x, w))
        x += w + gap
    return xs


def card_image(w: int, h: int, bg=(17, 24, 39), scale=1, radius=10):
    out = Image.new("RGB", (w * scale, h * scale), (0, 0, 0))
    card = Image.new("RGB", out.size, bg)
    out.paste(card, (0, 0), rounded_mask(out.size, radius * scale))
    return out


# ---------------------------------------------------------------------------- Uebertragung
_R5 = [v >> 3 for v in range(256)]
_G6 = [v >> 2 for v in range(256)]


def to_rgb565(img: Image.Image) -> bytes:
    """RGB565, hoeherwertiges Byte zuerst (so wie es das Deck speichert)."""
    img = img.convert("RGB")
    try:
        import numpy as np                              # schneller, falls vorhanden
        a = np.asarray(img, dtype=np.uint16)
        v = ((a[..., 0] >> 3) << 11) | ((a[..., 1] >> 2) << 5) | (a[..., 2] >> 3)
        return v.astype(">u2").tobytes()
    except ImportError:
        pass
    raw = img.tobytes()
    out = bytearray(len(raw) // 3 * 2)
    o = 0
    for i in range(0, len(raw), 3):
        v = (_R5[raw[i]] << 11) | (_G6[raw[i + 1]] << 5) | _R5[raw[i + 2]]
        out[o] = v >> 8
        out[o + 1] = v & 0xFF
        o += 2
    return bytes(out)


def rle(px: bytes) -> bytes:
    """Einfache Lauflaengen-Kodierung fuer 16-Bit-Pixel (siehe Firmware: dekodiere)."""
    n = len(px) // 2
    out = bytearray()
    i = 0
    lit_start = 0
    lit_len = 0

    def flush_literal(start, length):
        p = start
        while length > 0:
            c = min(length, 128)
            out.append(c - 1)
            out.extend(px[p * 2:(p + c) * 2])
            p += c
            length -= c

    while i < n:
        a, b = px[i * 2], px[i * 2 + 1]
        run = 1
        while i + run < n and run < 129 and px[(i + run) * 2] == a and px[(i + run) * 2 + 1] == b:
            run += 1
        if run >= 2:
            flush_literal(lit_start, lit_len)
            out.append(126 + run)
            out.extend((a, b))
            i += run
            lit_start, lit_len = i, 0
        else:
            if lit_len == 0:
                lit_start = i
            lit_len += 1
            i += 1
    flush_literal(lit_start, lit_len)
    return bytes(out)


def unrle(data: bytes, pixels: int) -> bytes:
    """Gegenstueck (fuer Tests und den Simulator)."""
    out = bytearray()
    i = 0
    while i < len(data) and len(out) < pixels * 2:
        c = data[i]; i += 1
        if c < 128:
            ln = (c + 1) * 2
            out += data[i:i + ln]; i += ln
        else:
            out += data[i:i + 2] * (c - 126); i += 2
    return bytes(out)


def encode(img: Image.Image) -> tuple[bytes, int]:
    """Bild -> (Bytes, z). Komprimiert nur, wenn es sich lohnt."""
    px = to_rgb565(img)
    z = rle(px)
    return (z, 1) if len(z) < len(px) else (px, 0)


def data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
