#!/usr/bin/env python3
"""Standalone canary proof-record checker (no writes, no auth minting).

Validates a structured proof JSON file (schema only, stdlib) and --
when ``DATABASE_URL`` is set and the backend deps are available --
cross-checks it against the durable DB ledger (READY rows + canonical
source). Never fetches B2 bytes itself and never mints auth: the
operator performs the B2 full-GET + Library authorized-route checks
with their own existing user session (see printed curl checklist) and
records the outcomes in the proof file; this script only verifies the
record is complete and consistent.

Proof schema (required)::

    {"video_uuid": "<uuid>", "source_sha256": "<64hex>",
     "source_revision_id": 123, "transform_version": "<v>",
     "slots": {"hq"|"light"|"poster": {"derivative_sha256": "<64hex>",
                                       "byte_size": 123}, ...},
     "checks": {"b2_full_get_sha_match": true, "ffprobe_clean": true,
                "frame_cadence_match": true, "library_auth_302": true,
                "range_206": true, "grant_expiry_checked": true,
                "logged_out_denied": true, "source_bytes_sha_match": true},
     "cadence_evidence": {"source_sha256": "<64hex>", "source_frames": 600,
                          "source_fps": 60.0, "source_duration": 10.0,
                          "outputs": {"light": {"frames": 600, ...}}, ...,
                          "vfr": false, "pts_exact_claimed": false},
     "recorded_at": "<ISO-8601>", "operator": "<name>"}

    ``cadence_evidence`` is REQUIRED when video slots (hq/light) are
    present: exact decoded frame count per video slot plus fps/duration
    tolerance (a 60->30 transcode fails); ``outputs`` covers exactly the
    video slots (poster is explicitly N/A, never listed);
    ``pts_exact_claimed`` is always false (per-frame PTS exactness is
    NOT proven by the bounded count census). Slots must be
    ``hq+light+poster``. ``light+poster`` (no HQ) is
    accepted ONLY with a server-trusted DB producer alias proof: the
    clip's ``web_package`` job ``finalized_slots`` pin matches the proof
    source/revision/version with ``hq_aliased_to == "light"`` (durable
    complete) AND the durable resolver still validates the alias.
    Anything else requires HQ (fail closed). The proof JSON claim alone
    never proves the alias.

Usage::

    python3 ops/canary_proof_check.py --proof ~/.config/.../proof-<uuid>.json
    # with DB cross-check (same runtime env as the server):
    DATABASE_URL='<runtime>' python3 ops/canary_proof_check.py --proof ... --db
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "ops"))


def _load_validator():
    import importlib.util as _ilu

    spec = _ilu.spec_from_file_location(
        "canary_web_package_check", REPO_ROOT / "ops" / "canary_web_package.py"
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check a canary proof record (no writes).")
    ap.add_argument("--proof", required=True, help="proof JSON file (private, OUTSIDE repo)")
    ap.add_argument("--db", action="store_true", help="also cross-check against the DB ledger")
    args = ap.parse_args(argv)

    ops = _load_validator()
    proof_path = Path(args.proof)
    try:
        raw = json.loads(proof_path.read_text())
    except Exception as exc:
        print(f"REFUSED: cannot read proof: {exc}")
        return 2
    try:
        norm = ops.validate_proof_record(raw)
    except ValueError as exc:
        print(f"REFUSED: {exc}")
        return 2
    print(f"schema OK: {norm['video_uuid'][:8]}... slots={sorted(norm['slots'])}")
    if args.db:
        import os

        if not os.environ.get("DATABASE_URL"):
            print("REFUSED: --db requires DATABASE_URL (runtime config; never printed).")
            return 2
        eng = ops._engine()
        db = ops._session(eng)
        try:
            ops.crosscheck_proof_db(db, norm)
        except ValueError as exc:
            print(f"REFUSED: {exc}")
            return 2
        finally:
            try:
                db.rollback()
            except Exception:
                pass
            try:
                db.close()
            except Exception:
                pass
        print("DB cross-check OK: READY ledger rows + canonical source match proof.")
    print("--- operator B2/Library evidence (run with YOUR user session; no minting) ---")
    print("  Preferred: python3 ops/canary_proof_collect.py --play-url <library-play-url>")
    print("    --library-origin <https://library-host> --storage-origin <https://b2-host>")
    print("    --cookies <private-cookie-file> --expired-url <expired-grant-same-object>")
    print("    (cookie ONLY to the Library origin, never auto-followed to storage;")
    print("     storage Range/full-GET/expiry-replay fetched WITHOUT credentials;")
    print("     grant_expiry_checked is true ONLY after a measured denial.)")
    print("  Manual equivalent (cookie discipline is mandatory, not optional):")
    print("    loc=$(curl -s -D - -o /dev/null -b 'session=<your-cookie>' '<play-url>' | grep -i '^location:')")
    print("    # 302 to a presigned storage URL expected; NEVER -L with -b (that leaks the cookie to storage).")
    print("    curl -s -D - -o /tmp/slot.bin \"$loc\"  # NO -b here: storage fetch carries no cookies")
    print("    sha256sum /tmp/slot.bin  # must equal ledger derivative_blob_sha256 (full bytes, never HEAD)")
    print("    ffprobe -v error -show_format -show_streams /tmp/slot.bin  # codec/tags/faststart clean")
    print("  Library auth: Range 206 with content-type; expired-grant replay denied (exact object,")
    print("  past timestamp, credential-free); logged-out denied with 401/403/404 ONLY (NO redirect")
    print("  counts -- not a grant, login, or same-origin playback redirect).")
    print("  Record all outcomes as true in proof.checks; any false keeps phase 2 blocked.")
    print("  NOT claimed: playback on a physical device browser stays unproven until a later")
    print("  device pass explicitly covers it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
