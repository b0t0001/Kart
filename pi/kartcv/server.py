"""Small HTTP control server (spec §9): /status, POST /reset, and an optional local debug page.

The debug page shows full camera frames, so it is off by default and never leaves the local network.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

import cv2

log = logging.getLogger(__name__)

_CROP_NAME = re.compile(r"^[\w-]+\.jpg$")
_CAM_PATH = re.compile(r"^/cam/(\d+)\.jpg$")

_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>KART cart vision</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{{font:14px system-ui;margin:16px;background:#111;color:#eee}}img.cam{{width:48%;margin:0 1% 8px 0;border:1px solid #444}}
li{{margin:6px 0;list-style:none}}li img{{height:56px;vertical-align:middle;margin-right:4px}}code{{color:#9cf}}</style></head>
<body><h3>KART cart vision · debug view (local only)</h3>{cams}<h4>Last events</h4><ul id="ev"></ul>
<script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c]);
setInterval(()=>{{for(const i of document.querySelectorAll('img.cam'))i.src=i.dataset.src+'t='+Date.now()}},500);
async function ev(){{const s=await (await fetch('/status')).json();
document.getElementById('ev').innerHTML=(s.last_events||[]).slice().reverse().map(e=>
`<li>${{(e.crops||[]).map(c=>`<img src="/crops/${{encodeURIComponent(c.split('/').pop())}}">`).join('')}}
<b>${{esc(e.type)}}</b> <code>${{esc(e.product_id??'?')}}</code> ${{esc(e.label)}} (${{esc(e.method)}} ${{(+e.confidence).toFixed(2)}})</li>`).join('')}}
ev();setInterval(ev,2000);
</script></body></html>"""


class ControlServer:
    def __init__(self, port: int, status_fn: Callable[[], dict], reset_fn: Callable[[], None],
                 frames_fn: Callable[[], dict] | None = None, debug_view: bool = False,
                 crops_dir: Path | None = None, host: str = "0.0.0.0", overlay_fn: Callable | None = None,
                 personal_fn: Callable[[str], bool] | None = None):
        self.status_fn, self.reset_fn, self.frames_fn = status_fn, reset_fn, frames_fn
        self.overlay_fn = overlay_fn  # (cam, img) -> img with the ROI outline; only when ?overlay=1
        self.personal_fn = personal_fn  # POST /personal {"event_id"}: "that's mine" from the iPad/backend
        self.debug_view = debug_view
        self.crops_dir = Path(crops_dir) if crops_dir else None
        self._httpd = ThreadingHTTPServer((host, port), self._handler())
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="control-server", daemon=True)

    def start(self) -> None:
        self._thread.start()
        log.info("control server on :%d (debug view %s)", self.port, "ON" if self.debug_view else "off")

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def _handler(self):
        srv = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):  # keep the cart's log readable
                pass

            def _send(self, code: int, body: bytes, ctype: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _404(self) -> None:
                self._send(404, b"not found", "text/plain")

            def do_GET(self):
                path = urllib.parse.urlparse(self.path).path
                if path == "/status":
                    return self._send(200, json.dumps(srv.status_fn(), default=str).encode(), "application/json")
                if not srv.debug_view:
                    return self._404()
                if path == "/":
                    cams = sorted((srv.frames_fn() or {}) if srv.frames_fn else {})
                    imgs = "".join(f'<img class="cam" data-src="/cam/{c}.jpg?overlay=1&" src="/cam/{c}.jpg?overlay=1" '
                                   f'alt="cam{c}">' for c in cams) or "<p>no camera frames yet</p>"
                    return self._send(200, _PAGE.format(cams=imgs).encode(), "text/html; charset=utf-8")
                m = _CAM_PATH.match(path)
                if m and srv.frames_fn:
                    img = (srv.frames_fn() or {}).get(int(m.group(1)))
                    if img is None:
                        return self._404()
                    query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                    if query.get("overlay", ["0"])[0] == "1" and srv.overlay_fn:  # raw unless asked: clips stay clean
                        img = srv.overlay_fn(int(m.group(1)), img)
                    q = query.get("q", ["70"])[0]
                    quality = min(95, max(30, int(q))) if q.isdigit() else 70  # remote recording asks for 95
                    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
                    return self._send(200, buf.tobytes(), "image/jpeg") if ok else self._404()
                if path.startswith("/crops/") and srv.crops_dir:
                    name = urllib.parse.unquote(path[len("/crops/"):])
                    f = srv.crops_dir / name
                    if _CROP_NAME.match(name) and f.is_file():
                        return self._send(200, f.read_bytes(), "image/jpeg")
                return self._404()

            def do_POST(self):
                path = urllib.parse.urlparse(self.path).path
                if path == "/reset":
                    srv.reset_fn()
                    return self._send(200, b'{"ok": true}', "application/json")
                if path == "/personal" and srv.personal_fn:
                    try:
                        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or b"{}")
                        event_id = str(body["event_id"])
                    except (ValueError, KeyError, TypeError):
                        return self._send(400, b'{"ok": false}', "application/json")
                    ok = bool(srv.personal_fn(event_id))
                    return self._send(200, json.dumps({"ok": ok}).encode(), "application/json")
                return self._404()

        return Handler

