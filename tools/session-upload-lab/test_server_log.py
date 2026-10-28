"""Lab server must never log the ?t=<TOKEN> page URL (stderr, no B2 I/O)."""
import io
import os
import sys

os.environ.setdefault("SESSION_LAB_BUCKET", "test-bucket")
os.environ.setdefault("SESSION_LAB_ENDPOINT", "https://s3.test.invalid")
os.environ.setdefault("SESSION_LAB_REGION", "test-1")
os.environ.setdefault("SESSION_LAB_KEY_ID", "test-id")
os.environ.setdefault("SESSION_LAB_KEY_SECRET", "test-secret")


def test_complete_retry_after_lost_response_reports_success(monkeypatch):
    import server
    calls = []

    class FakeS3:
        def head_object(self, Bucket, Key):
            calls.append("head")
            return {"ContentLength": 100}

        def generate_presigned_url(self, op, Params, ExpiresIn):
            return "https://play.test/x"

    monkeypatch.setattr(server, "s3", FakeS3())
    result = server.complete({"key": "lab/session-uploads/2026-10-28/abc-video.mov",
                              "uploadId": "consumed-id", "size": 100, "partSize": 50})
    assert result == {"ok": True, "size": 100, "playUrl": "https://play.test/x"}
    assert calls == ["head"]


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
