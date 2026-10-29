"""Regression checks for missing proxy credentials and false-green media health."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("media_delivery", ROOT / "ci/check-media-delivery.py")
media = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media)


class ProxyConfigurationTests(unittest.TestCase):
    def run_proxy(self, config, *args):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            env_dir = home / '.config/diveanalyzer'
            env_dir.mkdir(parents=True)
            (env_dir / 'browser-upload.env').write_text(config)
            (home / 'ci').mkdir()
            (home / 'ci/check-media-delivery.py').write_text('pass\n')
            binary = home / 'bin'
            binary.mkdir()
            # Compose refuses to proceed unless the managed key reached it.
            for name, body in {
                'git': 'exit 0',
                'docker-compose': 'test "$MEDIA_SIGNING_SECRET" = "' + 'a' * 64 + '" || exit 4\nprintf "%s\\n" "$*" >> "$HOME/compose-calls"',
                'docker': 'exit 0',
            }.items():
                path = binary / name
                path.write_text('#!/bin/sh\n' + body + '\n')
                path.chmod(0o755)
            env = {**os.environ, 'HOME': tmp, 'DIVE_DEPLOY_ROOT': tmp, 'PATH': str(binary) + ':' + os.environ['PATH']}
            # Reproduce a shell that lost its prior exported secret.
            env.pop('MEDIA_SIGNING_SECRET', None)
            result = subprocess.run(['bash', str(ROOT / 'ci/recreate-public-proxy.sh'), *args], env=env, capture_output=True, text=True)
            calls = (home / 'compose-calls').read_text() if (home / 'compose-calls').exists() else ''
            return result, calls

    def test_recreation_loads_backend_key_from_protected_file(self):
        result, calls = self.run_proxy('MEDIA_SIGNING_SECRET=' + 'a' * 64 + '\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--force-recreate funnel-proxy', calls)
        self.assertNotIn('a' * 64, result.stdout + result.stderr)

    def test_dry_run_validates_without_recreating(self):
        result, calls = self.run_proxy('MEDIA_SIGNING_SECRET=' + 'a' * 64 + '\n', '--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('config -q', calls)
        self.assertNotIn('up -d', calls)

    def test_missing_or_invalid_key_stops_before_compose(self):
        for config in ['', 'MEDIA_SIGNING_SECRET=invalid\n']:
            with self.subTest(config=config):
                result, calls = self.run_proxy(config)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, '')

    def test_manual_compose_recreation_requires_key(self):
        compose = (ROOT / 'ops/tailscale/docker-compose.yml').read_text()
        self.assertIn('${MEDIA_SIGNING_SECRET:?', compose)


class DeliveryTests(unittest.TestCase):
    def run_check(self, mode):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                valid = self.path.endswith('sig=a')
                status = 206 if valid else 403
                body = media.PAYLOAD[:8] if valid else b''
                if mode == 'missing_key':
                    status, body = 403, b''
                elif mode == 'missing_mount':
                    status, body = 404, b''
                elif mode == 'html':
                    status, body = 200, b'<html>'
                elif mode == 'tamper_allowed' and not valid:
                    status = 200
                elif mode == 'redirect':
                    status = 302
                self.send_response(status)
                if mode == 'redirect':
                    self.send_header('Location', '/login')
                self.end_headers()
                self.wfile.write(body)
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            media.verify(f'http://127.0.0.1:{server.server_port}', '/media/test?sig=a')
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_actual_range_bytes_and_tamper_rejection(self):
        self.run_check('healthy')

    def test_broken_delivery_cannot_pass_health(self):
        for mode in ['missing_key', 'missing_mount', 'html', 'tamper_allowed', 'redirect']:
            with self.subTest(mode=mode), self.assertRaises((RuntimeError, HTTPError)):
                self.run_check(mode)

    def test_failure_cleans_probe_and_does_not_log_capability(self):
        import io
        probe = '{"relative":"healthchecks/test.mp4","url":"/secret-capability"}'
        stderr = io.StringIO()
        with patch.object(media, 'backend', side_effect=[probe, '']) as backend, patch.object(media, 'verify', side_effect=RuntimeError('/secret-capability')), patch.object(sys, 'argv', ['check', '--base', 'http://localhost']), patch('sys.stderr', stderr):
            self.assertEqual(media.main(), 1)
        self.assertIn('.unlink(', backend.call_args.args[0])
        self.assertNotIn('/secret-capability', stderr.getvalue())
