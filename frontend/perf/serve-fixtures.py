#!/usr/bin/env python3
"""Serve two production builds against identical synthetic data, never production APIs."""
import argparse
import http.server
import json
import mimetypes
import threading
import time
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline', type=Path, required=True)
parser.add_argument('--candidate', type=Path, required=True)
parser.add_argument('--host', default='127.0.0.1')
parser.add_argument('--api-delay-ms', type=int, default=300)
parser.add_argument('--js-delay-ms', type=int, default=80)
args = parser.parse_args()
for directory in [args.baseline, args.candidate]:
    if not (directory / 'index.html').is_file():
        parser.error(f'{directory} must contain a production build')

DIVES = [dict(id=i, dive_code='103B', diver_id=1, performance='G', performance_numeric=3,
              height='1m', dive_datetime='2026-10-05T10:00:00', session_id=1,
              is_lineup=False, is_sync=False, platform_type='springboard', position='B',
              official_dd=1.5, phase1_performance='G', phase2_performance='G',
              raw_caption='103B G/G', video_uuid=f'fixture-{i}') for i in range(1, 2507)]


class Handler(http.server.BaseHTTPRequestHandler):
    def respond(self, body, mime, status=200):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path.startswith('/api/'):
            time.sleep(args.api_delay_ms / 1000)
            if path.endswith('/auth/me'):
                data = dict(user_id=1, email='benchmark@example.test', display_name='Benchmark',
                            is_admin=False, role='friend', divers=[])
            elif path.endswith('/dives'):
                data = DIVES
            elif path.endswith(('/by-height', '/by-direction')):
                data = {}
            elif path.endswith('/updates'):
                data = {'notes': []}
            else:
                data = []
            self.respond(json.dumps(data).encode(), 'application/json')
            return
        if path.startswith('/fixture/'):
            # No real video data: count attempts to load metadata in browser tools.
            self.respond(b'', 'video/mp4', 404)
            return
        root = (args.baseline if self.server.server_port == 4180 else args.candidate).resolve()
        file = (root / path.lstrip('/')).resolve()
        if root not in file.parents or not file.is_file():
            file = root / 'index.html'
        if file.suffix == '.js':
            time.sleep(args.js_delay_ms / 1000)
        self.respond(file.read_bytes(), mimetypes.guess_type(str(file))[0] or 'application/octet-stream')

    def do_POST(self):
        if self.path != '/api/v1/media/status/batch':
            self.respond(b'{}', 'application/json', 404)
            return
        time.sleep(args.api_delay_ms / 1000)
        payload = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
        data = {uuid: dict(status='ready', playback_url=f'/fixture/{uuid}.mp4', poster_url=None)
                for uuid in payload.get('video_uuids', [])}
        self.respond(json.dumps(data).encode(), 'application/json')

    def log_message(self, *unused):
        pass


for port in [4180, 4181]:
    server = http.server.ThreadingHTTPServer((args.host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
print('Baseline: 4180; candidate: 4181. Synthetic APIs only.', flush=True)
try:
    threading.Event().wait()
except KeyboardInterrupt:
    pass
