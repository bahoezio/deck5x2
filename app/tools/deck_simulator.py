"""Simuliert ein Deck (Firmware v0.3) ueber eine virtuelle serielle Schnittstelle.

Zum Testen der App ohne Hardware (Linux/macOS):
    python tools/deck_simulator.py      -> zeigt den Port, speichert das Bild als deck_sim.png
"""
import json
import os
import pty
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image  # noqa: E402

from deck import render  # noqa: E402

W, H = 480, 320


class Sim:
    def __init__(self):
        self.master, slave = pty.openpty()
        import tty
        tty.setraw(slave)
        self.port = os.ttyname(slave)
        self.fb = bytearray(W * H * 2)
        self.log = []
        self.anims = {}
        self.app = False
        self._buf = b""
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def send(self, msg):
        os.write(self.master, (json.dumps(msg) + "\n").encode())

    def press(self, i, hold=0.08):
        self.send({"t": "key", "i": i, "down": True})
        time.sleep(hold)
        self.send({"t": "key", "i": i, "down": False})

    def _read(self, n):
        while len(self._buf) < n:
            self._buf += os.read(self.master, 65536)
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _line(self):
        while b"\n" not in self._buf:
            self._buf += os.read(self.master, 65536)
        line, self._buf = self._buf.split(b"\n", 1)
        return line

    def _run(self):
        while self.running:
            try:
                line = self._line()
            except OSError:
                return
            try:
                m = json.loads(line)
            except ValueError:
                continue
            t = m.get("t")
            self.log.append(t)
            if t == "hello?":
                self.send({"t": "hello", "fw": "0.3.0", "device": "Deck 5x2", "keys": 10, "cal": True,
                           "caps": ["img", "anim", "rle", "touch", "sleep"]})
            elif t == "screen":
                self.app = m.get("app")
            elif t in ("img", "anim") and "n" in m:
                data = self._read(m["n"])
                frames = m.get("frames", 1)
                px = render.unrle(data, m["w"] * m["h"] * frames) if m.get("z") else data
                assert len(px) == m["w"] * m["h"] * 2 * frames, (t, len(px))
                first = px[:m["w"] * m["h"] * 2]
                for r in range(m["h"]):
                    o = ((m["y"] + r) * W + m["x"]) * 2
                    self.fb[o:o + m["w"] * 2] = first[r * m["w"] * 2:(r + 1) * m["w"] * 2]
                if t == "anim":
                    self.anims[m["slot"]] = (m["x"], m["y"], m["w"], m["h"], frames)
                self.send({"t": "ok", "for": t, "ok": True})
            elif t == "anim" and m.get("stop"):
                self.anims.pop(m.get("slot"), None)
            elif t == "getcal":
                self.send({"t": "cal", "v": [300, 3900, 310, 300, 3890, 3880, 3900, 310]})

    def image(self):
        out = Image.new("RGB", (W, H))
        px = out.load()
        for y in range(H):
            for x in range(W):
                o = (y * W + x) * 2
                v = (self.fb[o] << 8) | self.fb[o + 1]
                px[x, y] = ((v >> 11) << 3, ((v >> 5) & 63) << 2, (v & 31) << 3)
        return out


if __name__ == "__main__":
    s = Sim()
    print("Simuliertes Deck an", s.port)
    while True:
        time.sleep(3)
        s.image().save("deck_sim.png")
