"""Session upload lab: iPhone -> B2 direct multipart upload, served on the LAN.

The browser never sees a credential: this process signs one UploadPart URL
per chunk; bytes go straight from the phone to B2. Completion is verified
server-side (ListParts sizes + HEAD), so the browser does not need ETag.

Run via ./run.sh (loads ~/.config/dive-analyser/session-lab.env).
"""
import json
import os
import secrets
import sys
import time
import uuid
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import boto3
from botocore.config import Config

HERE = Path(__file__).resolve().parent
BUCKET = os.environ["SESSION_LAB_BUCKET"]
PREFIX = os.environ.get("SESSION_LAB_PREFIX", "lab/session-uploads")
TOKEN = os.environ.get("SESSION_LAB_TOKEN") or secrets.token_urlsafe(9)
PORT = int(os.environ.get("SESSION_LAB_PORT", "8791"))
LOG_DIR = Path(os.environ.get("SESSION_LAB_LOG_DIR", Path.home() / "Library/Logs/dive-session-lab"))
SIGN_TTL = 3600
MIN_PART = 5 * 1024 * 1024
MAX_PARTS = 10000

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["SESSION_LAB_ENDPOINT"],
    region_name=os.environ["SESSION_LAB_REGION"],
    aws_access_key_id=os.environ["SESSION_LAB_KEY_ID"],
    aws_secret_access_key=os.environ["SESSION_LAB_KEY_SECRET"],
    config=Config(signature_version="s3v4", retries={"total_max_attempts": 3}),
)


def _log(event: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    event = {"server_ts": datetime.now(timezone.utc).isoformat(), **event}
    with open(LOG_DIR / f"{datetime.now():%Y-%m-%d}.jsonl", "a") as fh:
        fh.write(json.dumps(event) + "\n")


def _own_key(key: str) -> str:
    if not isinstance(key, str) or not key.startswith(PREFIX + "/") or ".." in key:
        raise ValueError("bad key")
    return key


def _list_parts(key: str, upload_id: str) -> list:
    parts, marker = [], 0
    while True:
        page = s3.list_parts(Bucket=BUCKET, Key=key, UploadId=upload_id, PartNumberMarker=marker, MaxParts=1000)
        parts += [{"n": p["PartNumber"], "size": p["Size"], "etag": p["ETag"]} for p in page.get("Parts", [])]
        if not page.get("IsTruncated"):
            return parts
        marker = page["NextPartNumberMarker"]


def init(body):
    size, part_size = int(body["size"]), int(body["partSize"])
    if size <= 0 or part_size < MIN_PART or -(-size // part_size) > MAX_PARTS:
        raise ValueError("bad size/partSize")
    name = "".join(c for c in str(body.get("name") or "video")[-80:] if c.isalnum() or c in "._-") or "video"
    key = f"{PREFIX}/{datetime.now():%Y-%m-%d}/{uuid.uuid4().hex[:12]}-{name}"
    upload_id = s3.create_multipart_upload(Bucket=BUCKET, Key=key, ContentType=body.get("type") or "video/quicktime")["UploadId"]
    _log({"event": "server_init", "key": key, "size": size, "partSize": part_size})
    return {"key": key, "uploadId": upload_id}


def sign(body):
    key = _own_key(body["key"])
    urls = {
        int(n): s3.generate_presigned_url(
            "upload_part",
            Params={"Bucket": BUCKET, "Key": key, "UploadId": body["uploadId"], "PartNumber": int(n)},
            ExpiresIn=SIGN_TTL,
        )
        for n in body["parts"][:50]
    }
    return {"urls": urls, "ttl": SIGN_TTL}


def parts(body):
    return {"parts": _list_parts(_own_key(body["key"]), body["uploadId"])}


def complete(body):
    key, size, part_size = _own_key(body["key"]), int(body["size"]), int(body["partSize"])
    expected = -(-size // part_size)
    have = {p["n"]: p for p in _list_parts(key, body["uploadId"])}
    redo = [n for n in range(1, expected + 1)
            if have.get(n, {}).get("size") != (part_size if n < expected else size - part_size * (expected - 1))]
    if redo:
        _log({"event": "server_redo", "key": key, "redo": redo[:50], "sizes": {n: have.get(n, {}).get("size") for n in redo[:20]}})
        return {"ok": False, "redo": redo}
    t0 = time.monotonic()
    s3.complete_multipart_upload(
        Bucket=BUCKET, Key=key, UploadId=body["uploadId"],
        MultipartUpload={"Parts": [{"PartNumber": n, "ETag": have[n]["etag"]} for n in range(1, expected + 1)]},
    )
    head = s3.head_object(Bucket=BUCKET, Key=key)
    ok = head["ContentLength"] == size
    _log({"event": "server_complete", "key": key, "size": size, "verified": ok, "complete_ms": round((time.monotonic() - t0) * 1000)})
    return {"ok": ok, "size": head["ContentLength"], "playUrl": play_url(key)}


def play(body):
    return {"playUrl": play_url(_own_key(body["key"]))}


def play_url(key):
    return s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": key}, ExpiresIn=SIGN_TTL)


def abort(body):
    s3.abort_multipart_upload(Bucket=BUCKET, Key=_own_key(body["key"]), UploadId=body["uploadId"])
    _log({"event": "server_abort", "key": body["key"]})
    return {"ok": True}


def client_log(body):
    for event in body.get("events", [])[:200]:
        _log({"src": "client", **event})
    return {"ok": True}


ROUTES = {"/api/init": init, "/api/sign": sign, "/api/parts": parts, "/api/complete": complete,
          "/api/play": play, "/api/abort": abort, "/api/log": client_log}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE / "static"), **kw)

    def log_message(self, fmt, *args):
        requestline = str(args[0]) if args else ""
        if "/api/log" in requestline:
            return
        # The page URL carries ?t=<TOKEN> so a home-screen PWA keeps it;
        # the default handler would log that token to stderr, where it
        # authorizes API calls via X-Lab-Token. Log the path only.
        parts = requestline.split()
        if len(parts) >= 2:
            parts[1] = urlparse(parts[1]).path
            requestline = " ".join(parts)
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % tuple([requestline, *args[1:]])))

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if urlparse(self.path).path == "/":
            # The token rides in the page URL so a home-screen PWA keeps it.
            if parse_qs(urlparse(self.path).query).get("t", [""])[0] != TOKEN:
                return self._json(403, {"error": "token"})
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        route = ROUTES.get(urlparse(self.path).path)
        if route is None:
            return self._json(404, {"error": "not found"})
        if self.headers.get("X-Lab-Token") != TOKEN:
            return self._json(403, {"error": "token"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            return self._json(200, route(body))
        except Exception as exc:  # lab tool: surface the reason to the phone
            _log({"event": "server_error", "route": self.path, "error": f"{type(exc).__name__}: {exc}"[:300]})
            return self._json(500, {"error": f"{type(exc).__name__}: {exc}"[:300]})

    def _json(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    host = os.environ.get("SESSION_LAB_HOST", "0.0.0.0")
    lan = os.environ.get("SESSION_LAB_LAN_IP", "localhost")
    print(f"\n  Ouvre sur l'iPhone : http://{lan}:{PORT}/?t={TOKEN}\n  Logs : {LOG_DIR}\n", flush=True)
    ThreadingHTTPServer((host, PORT), Handler).serve_forever()
