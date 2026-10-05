"""Synthetic local API for reviewing the real React UI; no production access."""
import json
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/api/v1/auth/me':
            result = dict(user_id=98765, email='demo@example.invalid', display_name='Demo diver', role='friend', is_admin=False,
                          divers=[dict(diver_id=1, access_kind='OWNER')])
        elif path == '/api/v1/updates':
            root = Path(__file__).resolve().parents[3]
            note = json.loads((root / 'backend/release-notes/update-history.json').read_text())
            result = dict(schema=1, frontend_sha='a' * 40, notes=[{k: note[k] for k in ('id', 'date', 'title', 'body')}])
        elif path == '/api/v1/divers':
            result = [dict(id=1, display_name='Demo diver', is_primary_user=True)]
        elif path == '/api/v1/dives':
            result = [dict(id=i, dive_code=code, performance='G', performance_numeric=3, height='3m', dive_datetime='2026-10-05T17:00:00',
                           is_sync=False, diver_id=1, person_name='Demo diver', notes='', raw_caption='', video_uuid=None)
                      for i, code in enumerate(['103B', '101C', '403B'], 1)]
        else:
            self.send_response(404); self.end_headers(); return
        data = json.dumps(result).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data)))
        self.end_headers(); self.wfile.write(data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18766)
    args = parser.parse_args()
    HTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
