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
                "logged_out_denied": true},
     "recorded_at": "<ISO-8601>", "operator": "<name>"}

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
    print("  B2 full-GET: Library play URL (302) -> curl with session cookie -> sha256sum")
    print("    curl -sL -b 'session=<your-cookie>' -c /dev/null -D - -o /tmp/slot.bin '<play-url>'")
    print("    sha256sum /tmp/slot.bin  # must equal ledger derivative_blob_sha256 (full bytes, never HEAD)")
    print("    ffprobe -v error -show_format -show_streams /tmp/slot.bin  # codec/tags/faststart clean")
    print("  Library auth: Range 206 with content-type; expired-grant replay denied; logged-out denied.")
    print("  Record all outcomes as true in proof.checks; any false keeps phase 2 blocked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
