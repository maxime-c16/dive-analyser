#!/usr/bin/env python3
"""Smoke-test anonymous guest routing and account gates without a share secret."""
import sys
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    base = sys.argv[1].rstrip('/')
    opener = build_opener(NoRedirect)
    checks = [
        ('/share/0', 200),
        ('/claim', 200),
        # Public claim API (GET on a POST-only route: 405 proves it is past the gate).
        ('/api/v1/deposits/claim/peek', 405),
        ('/api/v1/deposits/claim/redeem', 405),
        ('/api/v1/deposits/pending', 401),
        ('/api/v1/shared-dives/0/social', 404),
        # Shared sessions: guest page/API reuse the /share/ and shared-dives
        # rules; the B2 hook is public but signature-checked (GET = 405, or
        # 404 while the feature is off).
        ('/share/session/0', 200),
        ('/api/v1/shared-dives/sessions/0/video', 404),
        ('/', 302),
        ('/share-not-public/0', 302),
        ('/api/v1/dives', 401),
        ('/api/v1/shared-dives-not-public/0', 401),
        ('/docs', 404),
        ('/adminer/', 404),
    ]
    for path, expected in checks:
        try:
            response = opener.open(base + path, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            assert response.code == expected, (path, response.code, expected)
            if expected == 302:
                assert response.headers.get('Location') == '/login', path
            if path == '/share/0':
                assert b'<html' in response.read().lower(), 'Guest page must load the SPA'
        print(f'{path}: {expected}')


if __name__ == '__main__':
    main()
