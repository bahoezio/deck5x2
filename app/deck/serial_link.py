"""Verbindung zum Deck ueber das USB-Kabel (serielle Schnittstelle, eine JSON-Zeile pro Nachricht)."""
import json
import logging
import threading
import time

import serial
from serial.tools import list_ports

log = logging.getLogger("deck.serial")

ESPRESSIF_VID = 0x303A        # USB-Hersteller-ID von Espressif (ESP32-S3 mit eigener USB-Buchse)
HEARTBEAT_S = 2.0
TIME_RESYNC_S = 300


def local_epoch() -> int:
    """Lokale Zeit als Sekunden (Sommerzeit eingerechnet). Das Deck zeigt sie direkt an."""
    now = time.time()
    return int(now + time.localtime(now).tm_gmtoff)


class DeckLink:
    """Sucht das Deck, haelt die Verbindung und meldet Ereignisse ueber Callbacks."""

    def __init__(self, on_key=None, on_status=None, on_message=None, port_hint=None):
        self.on_key = on_key or (lambda i, down: None)
        self.on_status = on_status or (lambda status: None)
        self.on_message = on_message or (lambda msg: None)
        self.port_hint = port_hint          # fuer Tests: fester Port
        self._ser = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.connected = False
        self.port = None
        self.info = {}
        self._on_connect_payloads = []      # Nachrichten, die nach jedem Verbinden geschickt werden
        self.time_sync = True
        self._ack = threading.Event()
        self._ack_ok = False
        self._bin_lock = threading.Lock()

    # ------------------------------------------------------------------ oeffentlich
    def start(self):
        self._thread = threading.Thread(target=self._run, name="deck-link", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._close()

    def set_on_connect(self, payloads):
        self._on_connect_payloads = list(payloads)

    def send(self, msg: dict) -> bool:
        data = (json.dumps(msg, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
        with self._lock:
            if not self._ser:
                return False
            try:
                self._ser.write(data)
                self._ser.flush()
                return True
            except (serial.SerialException, OSError) as e:
                log.warning("Senden fehlgeschlagen: %s", e)
                return False

    def send_binary(self, header: dict, payload: bytes, timeout: float = 4.0) -> bool:
        """JSON-Kopf (mit n = Anzahl Bytes), direkt danach die Bilddaten. Dann auf die Bestaetigung
        des Decks warten, bevor das naechste Bild kommt (sonst laeuft sein Empfangspuffer ueber)."""
        header = dict(header, n=len(payload))
        data = (json.dumps(header, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
        with self._bin_lock:
            self._ack.clear()
            with self._lock:
                if not self._ser:
                    return False
                try:
                    self._ser.write(data)
                    view = memoryview(payload)
                    for k in range(0, len(payload), 8192):
                        self._ser.write(view[k:k + 8192])
                    self._ser.flush()
                except (serial.SerialException, OSError) as e:
                    log.warning("Bild senden fehlgeschlagen: %s", e)
                    return False
            if not self._ack.wait(timeout + len(payload) / 200_000):
                log.warning("Deck hat das Bild nicht bestaetigt (%s, %d Bytes)", header.get("t"), len(payload))
                time.sleep(1.2)                 # Deck bricht den Empfang nach 1 s selbst ab
                return False
            if not self._ack_ok:
                log.warning("Deck meldet Fehler beim Bild (%s)", header)
            return self._ack_ok

    def has(self, cap: str) -> bool:
        return cap in (self.info.get("caps") or [])

    def send_time(self):
        return self.send({"t": "time", "local": local_epoch()})

    # ------------------------------------------------------------------ intern
    def _candidates(self):
        if self.port_hint:
            return [self.port_hint]
        ports = [p.device for p in list_ports.comports() if p.vid == ESPRESSIF_VID]
        return ports

    def _close(self):
        with self._lock:
            if self._ser:
                try:
                    self._ser.close()
                except Exception:
                    pass
            self._ser = None
        if self.connected:
            self.connected = False
            self.on_status(self.status())

    def status(self):
        return {"connected": self.connected, "port": self.port, "fw": self.info.get("fw"),
                "calibrated": self.info.get("cal"), "caps": self.info.get("caps") or [],
                "light": bool(self.info.get("light"))}

    def _try_open(self, port):
        try:
            s = serial.Serial(port, 115200, timeout=0.05, write_timeout=10)
        except (serial.SerialException, OSError) as e:
            log.debug("Port %s nicht offen: %s", port, e)
            return False
        with self._lock:
            self._ser = s
        # Begruessung abfragen; das Deck antwortet mit {"t":"hello",...}
        self.send({"t": "hello?"})
        deadline = time.time() + 2.5
        buf = b""
        while time.time() < deadline and not self._stop.is_set():
            try:
                buf += s.read(256)
            except (serial.SerialException, OSError):
                break
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                msg = self._parse(line)
                if msg and msg.get("t") == "hello":
                    self.info = msg
                    self.port = port
                    self.connected = True
                    self._rest = buf
                    log.info("Deck verbunden an %s (Firmware %s)", port, msg.get("fw"))
                    return True
        self._close()
        return False

    @staticmethod
    def _parse(line: bytes):
        try:
            msg = json.loads(line.decode("utf-8", "replace").strip() or "null")
            return msg if isinstance(msg, dict) else None
        except ValueError:
            return None

    def _run(self):
        while not self._stop.is_set():
            if not self.connected:
                for port in self._candidates():
                    if self._try_open(port):
                        break
                if not self.connected:
                    self._stop.wait(2.0)
                    continue
                self.on_status(self.status())
                if self.time_sync:
                    self.send_time()
                for p in self._on_connect_payloads:
                    self.send(p)
                self._session()

    def _session(self):
        buf = getattr(self, "_rest", b"")
        last_hb = 0.0
        last_time = time.time()
        while not self._stop.is_set() and self.connected:
            now = time.time()
            if now - last_hb > HEARTBEAT_S:
                if not self.send({"t": "hb"}):
                    break
                last_hb = now
            if self.time_sync and now - last_time > TIME_RESYNC_S:
                self.send_time()
                last_time = now
            try:
                with self._lock:
                    s = self._ser
                if not s:
                    break
                chunk = s.read(s.in_waiting or 1)
            except (serial.SerialException, OSError, TypeError, AttributeError):
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                msg = self._parse(line)
                if not msg:
                    continue
                if msg.get("t") == "key":
                    try:
                        self.on_key(int(msg.get("i", -1)), bool(msg.get("down")))
                    except Exception:
                        log.exception("Fehler bei Tastendruck")
                elif msg.get("t") == "ok" and msg.get("for") in ("img", "anim"):
                    self._ack_ok = bool(msg.get("ok", True))
                    self._ack.set()
                elif msg.get("t") == "hello":
                    self.info = msg
                    self.on_status(self.status())
                else:
                    if msg.get("t") == "cal":
                        self.info["cal"] = True
                        self.info["cal_values"] = msg.get("v")
                    self.on_message(msg)
        log.info("Verbindung zum Deck getrennt")
        self._close()
