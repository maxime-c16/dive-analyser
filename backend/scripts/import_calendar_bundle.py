#!/usr/bin/env python
"""Reviewed calendar import CLI (Task03). See app/services/calendar_import.py.

Steps (each explicit; nothing is applied by validate or preview):
    validate --bundle B
    preview  --bundle B --database-url URL --club kcpm --group beginners=SLUG[:Name] ...
             --artifact-dir DIR [--create-club NAME] [--create-missing-groups] [--plan-out FILE]
    apply    (same arguments) --plan-hash HASH [--batch ID]
    review   --database-url URL --club kcpm
    resolve  --database-url URL --club kcpm --key EXTERNAL_KEY [--accept-source]

--database-url is mandatory and never defaulted from the app environment,
so a production database is only touched on purpose. --artifact-dir is
private storage outside Git (content-addressed, files mode 0600).
The bundle, its sources and any --plan-out file are private data: never
commit them.
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.models  # noqa: E402,F401  (register every mapped table)
from app.models.user_auth import AppUser  # noqa: E402
from app.services import calendar_import as ci  # noqa: E402


def group_arg(value: str):
    key, _, rest = value.partition("=")
    slug, _, name = rest.partition(":")
    if not key or not slug:
        raise argparse.ArgumentTypeError("use KEY=SLUG[:Display name]")
    return key, (slug, name or slug)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--bundle", type=Path, required=True)
    for name in ("preview", "apply"):
        c = sub.add_parser(name)
        c.add_argument("--bundle", type=Path, required=True)
        c.add_argument("--database-url", required=True)
        c.add_argument("--club", required=True)
        c.add_argument("--group", type=group_arg, action="append", required=True)
        c.add_argument("--artifact-dir", type=Path, required=True)
        c.add_argument("--season-start", type=date.fromisoformat, default=date(2026, 9, 1))
        c.add_argument("--create-club")
        c.add_argument("--create-missing-groups", action="store_true")
        c.add_argument("--actor-email")
        if name == "preview":
            c.add_argument("--plan-out", type=Path, help="write the full plan (private) for review")
        else:
            c.add_argument("--plan-hash", required=True)
            c.add_argument("--batch")
    r = sub.add_parser("review")
    r.add_argument("--database-url", required=True)
    r.add_argument("--club", required=True)
    x = sub.add_parser("resolve")
    x.add_argument("--database-url", required=True)
    x.add_argument("--club", required=True)
    x.add_argument("--key", required=True)
    x.add_argument("--accept-source", action="store_true")
    return p


def apply_hint(result: dict) -> str:
    hint = f"Review, then apply with: --plan-hash {result['plan_hash']}"
    if result["batch_id"] is not None:
        hint += f" --batch {result['batch_id']}"
    return hint


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "validate":
            print(json.dumps(ci.validate(ci.load_bundle(args.bundle)), indent=2))
            return 0
        db = sessionmaker(bind=create_engine(args.database_url))()
        if args.command == "review":
            print(json.dumps(ci.review_queue(db, args.club), indent=2, ensure_ascii=False))
            return 0
        if args.command == "resolve":
            print(json.dumps(ci.resolve(db, args.club, args.key, args.accept_source), indent=2))
            return 0
        bundle = ci.load_bundle(args.bundle)
        opts = ci.Options(club_slug=args.club, groups=dict(args.group), season_start=args.season_start,
                          create_club_name=args.create_club, create_missing_groups=args.create_missing_groups)
        actor = db.query(AppUser).filter(AppUser.email == args.actor_email).one_or_none() if args.actor_email else None
        if args.actor_email and actor is None:
            raise ci.ImportError_("--actor-email does not match an account")
        if args.command == "preview":
            result = ci.preview(db, bundle, opts, args.artifact_dir, actor)
            if args.plan_out:
                args.plan_out.write_text(json.dumps(result["plan"], indent=2, ensure_ascii=False, default=str))
                os.chmod(args.plan_out, 0o600)
            out = {k: v for k, v in result.items() if k != "plan"}
            out["review"] = [{"key": c["key"], "title": c["title"], "disposition": c["disposition"],
                              "issue": c["provenance"]["issue"]} for c in result["plan"]["competitions"]
                             if c["disposition"] == "needs_review"]
            out["conflicts"] = [x for t in result["plan"]["training"] for x in t["conflict"]]
            out["missing_from_source"] = [x for t in result["plan"]["training"] for x in t["missing_from_source"]]
            print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
            print("\n" + apply_hint(result), file=sys.stderr)
            return 0
        result = ci.apply(db, bundle, opts, args.artifact_dir, actor, args.plan_hash, args.batch)
        print(json.dumps(result, indent=2))
        return 0
    except ci.ImportError_ as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
