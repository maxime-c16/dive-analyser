"""Local synthetic byte counter, no production access.
python3 docs/audits/media-startup-opus/lot3_fixture_server.py
Serve alongside Vite 3022. /stats reports actual bytes written for video requests.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import threading

ROOT = Path(__file__).resolve().parents[3] / 'frontend/node_modules/.cache'
TOTAL = {'preview': 0, 'light': 0}
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        name = self.path.split('?')[0].strip('/')
        if name == 'stats':
            with LOCK:
                data = json.dumps(TOTAL).encode()
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(data)
            return
        if name not in TOTAL:
            self.send_error(404)
            return
        path = ROOT / f'library-{name}-synthetic.mp4'
        data = path.read_bytes()
        start, end = 0, len(data) - 1
        ranged = self.headers.get('Range')
        if ranged:
            first, last = ranged.removeprefix('bytes=').split('-')
            start = int(first or 0)
            end = min(int(last) if last else end, end)
        payload = data[start:end + 1]
        self.send_response(206 if ranged else 200)
        self.send_header('Content-Type', 'video/mp4')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Accept-Ranges', 'bytes')
        if ranged:
            self.send_header('Content-Range', f'bytes {start}-{end}/{len(data)}')
        self.end_headers()
        try:
            self.wfile.write(payload)
            with LOCK:
                TOTAL[name] += len(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 3023), Handler).serve_forever()
