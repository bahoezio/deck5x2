"""Oberflaeche im normalen Browser testen (ohne pywebview), mit echter App-Logik und simuliertem Deck.

    python tools/ui_dev_server.py      -> http://127.0.0.1:8765
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import deck_app  # noqa: E402
from deck.engine import Engine  # noqa: E402

SHIM = """<script>
window.pywebview={api:new Proxy({},{get:(_,name)=>async(...args)=>{
  const r=await fetch('/api/'+name,{method:'POST',body:JSON.stringify(args)});return r.json()}})};
setTimeout(()=>window.dispatchEvent(new Event('pywebviewready')),0);
</script>"""


def make_handler(api):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8").replace("<script>", SHIM + "<script>", 1)
            data = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            name = self.path.rsplit("/", 1)[-1]
            args = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"[]")
            fn = getattr(api, name, None)
            res = fn(*args) if fn and not name.startswith("_") else None
            data = json.dumps(res).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)
    return H


def main(port=8765, simulate=True):
    app = Engine()
    if simulate:
        from deck_simulator import Sim
        sim = Sim()
        app.link.port_hint = sim.port
        app.sim = sim
    app.start()
    api = deck_app.Api(app)
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(api))
    print(f"http://127.0.0.1:{port}")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return app, srv


if __name__ == "__main__":
    main()
    threading.Event().wait()
