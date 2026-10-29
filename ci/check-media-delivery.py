#!/usr/bin/env python3
"""Exercise signed bytes through both front doors without logging capabilities."""
import argparse
import json
import ssl
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

PAYLOAD = b"dive-media-delivery-healthcheck\n"


def backend(code):
    return subprocess.run(
        ["docker", "exec", "-i", "dive-analyser-backend-1", "python", "-c", code],
        check=True, capture_output=True, text=True, timeout=20,
    ).stdout.strip()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def verify(base, url, payload=PAYLOAD):
    # Only the fixed loopback LAN endpoint has a self-signed certificate.
    context = ssl._create_unverified_context() if base == "https://127.0.0.1:6443" else ssl.create_default_context()
    opener = build_opener(NoRedirect(), HTTPSHandler(context=context))
    # A redirect or HTML response must not count as media delivery.
    try:
        with opener.open(Request(base.rstrip("/") + url, headers={"Range": "bytes=0-7"}), timeout=15) as response:
            if response.status != 206 or response.read(9) != payload[:8]:
                raise RuntimeError("signed media Range/bytes check failed")
    except HTTPError as error:
        error.close()
        raise RuntimeError("signed media HTTP check failed") from None
    # Tampering with a capability must still fail closed.
    invalid = url[:-1] + ("0" if url[-1] != "0" else "1")
    try:
        with opener.open(base.rstrip("/") + invalid, timeout=15):
            raise RuntimeError("invalid media signature was accepted")
    except HTTPError as error:
        with error:
            if error.code != 403:
                raise RuntimeError("invalid media signature did not return 403") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", action="append", required=True)
    args = parser.parse_args()
    probe = None
    try:
        # A tiny disposable artifact tests the actual shared cache mount too.
        # Mint using the running backend, not a separate copy of its secret.
        probe = json.loads(backend('''
import hashlib, json, os, uuid
from pathlib import Path
from app.config import get_settings
from app.services.signed_media import signed_url
if os.environ.get("MEDIA_SIGNED_URLS_ENABLED", "false").lower() != "true":
 print(json.dumps({"disabled": True}))
else:
 root = Path(get_settings().media_cache_root)
 relative = "healthchecks/" + uuid.uuid4().hex + ".mp4"
 path = root / relative
 path.parent.mkdir(parents=True, exist_ok=True)
 payload = b"dive-media-delivery-healthcheck\\n"
 url = signed_url(path, hashlib.sha256(payload).hexdigest())
 if not url:
  raise RuntimeError("Backend signing configuration invalid")
 path.write_bytes(payload)
 print(json.dumps({"relative": relative, "url": url}))
'''))
        if probe.get("disabled"):
            print("Signed media disabled; delivery probe skipped")
            return 0
        for index, base in enumerate(args.base, 1):
            verify(base, probe["url"])
            print(f"Signed media front door {index}: bytes, Range and signature rejection verified")
        return 0
    except Exception:
        # HTTP/subprocess exceptions can contain signed URLs or secret config.
        print("Signed media delivery FAILED; check signing configuration and shared cache mounts", file=sys.stderr)
        return 1
    finally:
        if probe and probe.get("relative"):
            try:
                backend("from pathlib import Path; from app.config import get_settings; "
                        f"(Path(get_settings().media_cache_root) / {probe['relative']!r}).unlink(missing_ok=True)")
            except Exception:
                print("Media probe cleanup failed", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
