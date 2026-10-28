"""One-time B2 setup for the session upload lab (stdlib only).

With a key restricted to the (UI-created) sessions bucket, it configures that
bucket and reuses the key for the lab. With an account key it can also create
the bucket and mint a bucket-scoped key. Either way it:
  - makes the bucket private,
  - allow browser PUT/GET from the given origins (CORS; the B2 web UI can
    only create download-only rules),
  - cancel unfinished multipart uploads after 3 days and expire lab/ files
    after 30 days,
  - writes the bucket-scoped key to ~/.config/dive-analyser/session-lab.env
    (mode 600). An account key is read from a file and never written.

    python3 b2_setup.py --master-key-file PATH --origin http://192.168.1.151:8791
"""
import argparse
import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

ENV_FILE = Path.home() / ".config/dive-analyser/session-lab.env"
# Source-safety boundary: the lab credential must never reach outside lab/.
# The server key gate (server.py `_own_key`) only constrains paths passed to
# the lab server itself; a leaked or reused bucket-wide key could overwrite
# or delete session originals under inbox/.
LAB_PREFIX = "lab/"


def read_master(path: str) -> tuple:
    text = Path(path).read_text().strip()
    kv = dict(re.findall(r"^\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*['\"]?([^'\"\s]+)", text, re.M))
    key_id = next((v for k, v in kv.items() if "ID" in k), None)
    secret = next((v for k, v in kv.items() if "ID" not in k and ("KEY" in k or "SECRET" in k)), None)
    if key_id and secret:
        return key_id, secret
    tokens = re.split(r"[\s:]+", text)
    if len(tokens) == 2:
        return tokens[0], tokens[1]
    raise SystemExit("master key file: expected 'keyId:applicationKey' (or two lines / KEY_ID=, KEY=)")


def call(url, token, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Authorization": token, "Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as exc:
        return {"_error": exc.code, **json.loads(exc.read() or b"{}")}


def lab_prefix_ok(allowed: dict) -> bool:
    """An existing bucket-restricted key is reusable only when its namePrefix
    stays inside lab/ (None or empty means bucket-wide: reject)."""
    prefix = (allowed or {}).get("namePrefix") or ""
    return prefix == LAB_PREFIX or prefix.startswith(LAB_PREFIX)


def _normalized(rule: dict) -> dict:
    """Order-insensitive comparison for the list-valued rule settings."""
    normalized = dict(rule or {})
    for key in ("allowedOrigins", "allowedOperations", "allowedHeaders", "exposeHeaders"):
        if isinstance(normalized.get(key), list):
            normalized[key] = sorted(map(str, normalized[key]))
    return normalized


def existing_rules_intact(existing: dict, cors: list, lifecycle: list) -> bool:
    """Fail closed before overwriting bucket config: b2_update_bucket
    REPLACES every CORS/lifecycle rule, so an existing bucket carrying
    production playback origins (or other rules) must never be silently
    reset to the lab-only set — even under a familiar rule name. Every
    existing rule must match a wanted rule setting-for-setting."""
    current_cors = (existing or {}).get("corsRules") or []
    current_lifecycle = (existing or {}).get("lifecycleRules") or []
    wanted_cors = [_normalized(rule) for rule in cors]
    wanted_lifecycle = [_normalized(rule) for rule in lifecycle]
    return (all(_normalized(rule) in wanted_cors for rule in current_cors)
            and all(_normalized(rule) in wanted_lifecycle for rule in current_lifecycle))


def bucket_rules_known(existing: dict) -> bool:
    """b2_list_buckets must expose the current rules for the guard above;
    without them, overwriting is unverifiable and must not proceed."""
    return isinstance((existing or {}).get("corsRules"), list) and isinstance((existing or {}).get("lifecycleRules"), list)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--master-key-file", required=True)
    ap.add_argument("--bucket", default="diveanalyzer-sessions")
    ap.add_argument("--origin", action="append", required=True)
    args = ap.parse_args()

    key_id, secret = read_master(args.master_key_file)
    basic = base64.b64encode(f"{key_id}:{secret}".encode()).decode()
    auth = json.load(urllib.request.urlopen(urllib.request.Request(
        "https://api.backblazeb2.com/b2api/v2/b2_authorize_account", headers={"Authorization": "Basic " + basic}), timeout=30))
    api, token, account = auth["apiUrl"] + "/b2api/v2/", auth["authorizationToken"], auth["accountId"]
    allowed = auth.get("allowed") or {}
    if allowed.get("bucketId") and allowed.get("bucketName") != args.bucket:
        raise SystemExit(f"This key is restricted to another bucket ({allowed.get('bucketName')}); expected {args.bucket}.")

    cors = [{
        "corsRuleName": "sessionLabBrowser",
        "allowedOrigins": args.origin,
        "allowedOperations": ["s3_put", "s3_get", "s3_head"],
        "allowedHeaders": ["*"],
        "exposeHeaders": ["ETag", "Content-Length", "Content-Range", "Accept-Ranges"],
        "maxAgeSeconds": 3600,
    }]
    lifecycle = [{
        "fileNamePrefix": "lab/",
        "daysFromUploadingToHiding": 30,
        "daysFromHidingToDeleting": 1,
        "daysFromStartingToCancelingUnfinishedLargeFiles": 3,
    }]

    found = call(api + "b2_list_buckets", token, {"accountId": account, "bucketName": args.bucket}).get("buckets") or []
    if found:
        if not bucket_rules_known(found[0]) or not existing_rules_intact(found[0], cors, lifecycle):
            raise SystemExit(
                f"bucket {args.bucket} carries unverifiable or non-lab CORS/lifecycle rules; refusing to overwrite them "
                "(rerunning setup would drop production playback origins). Merge them explicitly first.")
        bucket = call(api + "b2_update_bucket", token, {"accountId": account, "bucketId": found[0]["bucketId"], "bucketType": "allPrivate", "corsRules": cors, "lifecycleRules": lifecycle})
        print("bucket updated:", args.bucket)
    else:
        bucket = call(api + "b2_create_bucket", token, {"accountId": account, "bucketName": args.bucket, "bucketType": "allPrivate", "corsRules": cors, "lifecycleRules": lifecycle})
        print("bucket created:", args.bucket)
    if "_error" in bucket:
        raise SystemExit(f"bucket: {bucket}")

    if allowed.get("bucketId"):
        if not lab_prefix_ok(allowed):
            raise SystemExit(
                "This key is not restricted to lab/: recreate a lab/-prefixed key with the master key "
                "(bucket-wide lab keys can overwrite or delete session originals outside lab/).")
        new_key = {"applicationKeyId": key_id, "applicationKey": secret}
    else:
        new_key = call(api + "b2_create_key", token, {
            "accountId": account, "keyName": "session-upload-lab", "bucketId": bucket["bucketId"],
            "capabilities": ["listFiles", "readFiles", "writeFiles", "deleteFiles"],
            "namePrefix": LAB_PREFIX,
        })
        if "_error" in new_key:
            raise SystemExit(f"key: {new_key}")

    region = re.search(r"s3\.([a-z0-9-]+)\.backblazeb2\.com", auth["s3ApiUrl"]).group(1)
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(f"SESSION_LAB_BUCKET={args.bucket}\nSESSION_LAB_ENDPOINT={auth['s3ApiUrl']}\nSESSION_LAB_REGION={region}\n"
                 f"SESSION_LAB_KEY_ID={new_key['applicationKeyId']}\nSESSION_LAB_KEY_SECRET={new_key['applicationKey']}\n")
    print(f"bucket-scoped key written to {ENV_FILE} (600); CORS origins: {', '.join(args.origin)}")


if __name__ == "__main__":
    main()
