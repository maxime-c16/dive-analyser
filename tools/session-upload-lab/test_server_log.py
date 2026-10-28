"""Lab server must never log the ?t=<TOKEN> page URL (stderr, no B2 I/O)."""
import io
import os
import sys

os.environ.setdefault("SESSION_LAB_BUCKET", "test-bucket")
os.environ.setdefault("SESSION_LAB_ENDPOINT", "https://s3.test.invalid")
os.environ.setdefault("SESSION_LAB_REGION", "test-1")
os.environ.setdefault("SESSION_LAB_KEY_ID", "test-id")
os.environ.setdefault("SESSION_LAB_KEY_SECRET", "test-secret")


def test_access_log_strips_page_token():
    from server import Handler
    handler = Handler.__new__(Handler)
    buffer = io.StringIO()
    previous, sys.stderr = sys.stderr, buffer
    try:
        handler.log_message('"%s" %s %s', 'GET /?t=SUPERSECRET HTTP/1.1', '', '')
        handler.log_message('"%s" %s %s', 'POST /api/sign HTTP/1.1', '', '')
    finally:
        sys.stderr = previous
    output = buffer.getvalue()
    assert 'SUPERSECRET' not in output
    assert 'GET / ' in output and '/api/sign' in output
