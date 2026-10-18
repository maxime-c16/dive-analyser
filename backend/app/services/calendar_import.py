"""Reviewed calendar import: validate -> preview/review -> explicit apply.

Input is the private bundle written by scripts/prepare_calendar_sources.py
plus the source files it hashes. Nothing here fetches a URL: embedded
workbook links become an inventory of child calendar_sources only.

- validate(): pure checks (format, artifact hashes, unique keys, local->UTC
  times, date ranges). No database access.
- build_plan(): read-only diff against the database. Deterministic, so its
  sha256 (plan_hash) identifies exactly what a reviewer saw.
- preview(): stores artifacts in private storage, upserts source metadata
  and records one calendar_import_runs row per artifact (status previewed)
  sharing a batch id and the plan hash. No calendar content is written.
- apply(): recomputes the plan, refuses if it differs from the preview
  (data or database changed since review), then writes everything in ONE
  transaction and marks the runs applied.

Identity rules: training occurrences map by the bundle source_key
(club:season:group:date), which excludes time and venue, so a corrected time
or venue updates the same occurrence and keeps responses. A date or group
change appears as a new key plus a ``missing_from_source`` review item; a
missing row never cancels anything. Records edited in the app
(locally_overridden) produce ``conflict`` items instead of being overwritten.
Competition candidates never publish: future dated ones become draft club
events for curator review; undated/malformed ones and past seasons stay as
mapping-only review/historical items with their raw cells as provenance.
"""
import hashlib
import json
import os
import re
import shutil
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.calendar import (
    Calendar, CalendarEvent, CalendarImportRun, CalendarSource, CalendarSourceMapping, Club, EventOccurrence,
    EventResource, TrainingGroup,
)
from app.models.user_auth import AppUser
from app.services import calendar_events as events

PARSER_VERSION = "kcpm-bundle-v1"
FEDERATION_HOSTS = ("ffnatation.fr", "extranat.fr", "lif-natation.fr", "worldaquatics.com", "len.eu",
                    "europeanaquatics.org")
PRIVATE_HOSTS = ("docs.google.com", "drive.google.com", "sites.google.com", "facebook.com", "forms.gle")
# Competition sheet columns (header row 3 of the supplied workbook).
LINK_COLUMNS = {"E": ("official_info", "Infos / site"), "G": ("other", "Infos supplémentaires"),
                "H": ("dive_sheets", "Dive Recorder"), "I": ("club_chat", "Groupe WhatsApp"),
                "J": ("results", "Résultats")}
RESOURCE_KINDS = {"Fédé": "official_info", "Compét": "official_info", "Docs": "rules", "Stages": "other",
                  "Autres": "other"}


class ImportError_(Exception):
    """Validation or apply refusal; message is operator-facing."""


def is_whatsapp(url: Optional[str]) -> bool:
    return bool(url) and "chat.whatsapp.com" in url


def slug(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:60] or "untitled"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- Validation --------------------------------------------------------------------

@dataclass
class Bundle:
    data: dict
    path: Path
    files: dict = field(default_factory=dict)  # source key -> resolved Path
    sha256: str = ""


def resolve_source(bundle_path: Path, ref: str) -> Path:
    """Bundle paths are repo-relative; also accept a sibling sources/ dir."""
    candidates = [Path(ref), bundle_path.parent / "sources" / Path(ref).name]
    for parent in bundle_path.resolve().parents:
        candidates.append(parent / ref)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ImportError_(f"Source artifact not found: {ref}")


def load_bundle(path: Path) -> Bundle:
    raw = path.read_bytes()
    return Bundle(data=json.loads(raw), path=path, sha256=hashlib.sha256(raw).hexdigest())


def validate(bundle: Bundle) -> dict:
    """Raise ImportError_ listing every problem; return counts when valid."""
    data, errors = bundle.data, []
    if data.get("format_version") != 1:
        errors.append("Unsupported bundle format_version")
    sources = data.get("sources") or {}
    for key in ("beginners", "advanced", "workbook"):
        ref = sources.get(key) or {}
        try:
            path = resolve_source(bundle.path, ref.get("file", ""))
            if sha256_file(path) != ref.get("sha256"):
                errors.append(f"Artifact hash mismatch for {key}")
            bundle.files[key] = path
        except ImportError_ as exc:
            errors.append(str(exc))
    hashes = {ref.get("sha256") for ref in sources.values()}
    rows = data.get("training_occurrences") or []
    keys = [r.get("source_key") for r in rows]
    if len(set(keys)) != len(keys):
        errors.append("Duplicate training source keys")
    for r in rows:
        key = r.get("source_key") or ""
        parts = key.split(":")
        try:
            day = date.fromisoformat(r["local_date"])
            if len(parts) != 4 or parts[2] != r["group_key"] or parts[3] != r["local_date"]:
                raise ValueError("source key does not match group/date")
            tz = ZoneInfo(r["timezone"])
            for local, utc in (("start_local", "start_at"), ("end_local", "end_at")):
                hh, mm = map(int, r[local].split(":"))
                expected = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz).astimezone(timezone.utc)
                if expected != datetime.fromisoformat(r[utc]):
                    raise ValueError(f"{utc} disagrees with {local} in {r['timezone']}")
            if r["end_local"] <= r["start_local"]:
                raise ValueError("end before start")
            if r["source"]["sha256"] not in hashes:
                raise ValueError("row cites an unknown artifact")
        except (KeyError, ValueError, TypeError) as exc:
            errors.append(f"Training row {key or '?'}: {exc}")
    for meet in data.get("competition_candidates") or []:
        if not (meet.get("title") or "").strip():
            errors.append(f"Competition row {meet.get('source', {}).get('row')}: missing title")
        if meet.get("start_date") and meet.get("end_date_exclusive"):
            if meet["end_date_exclusive"] <= meet["start_date"]:
                errors.append(f"Competition row {meet['source']['row']}: reversed range")
    if errors:
        raise ImportError_("Bundle validation failed:\n- " + "\n- ".join(errors))
    groups = sorted({r["group_key"] for r in rows})
    return {"training_occurrences": len(rows), "groups": groups,
            "per_group": {g: sum(1 for r in rows if r["group_key"] == g) for g in groups},
            "competition_candidates": len(data.get("competition_candidates") or []),
            "resources": len(data.get("resources") or []), "bundle_sha256": bundle.sha256}


# --- Options and source identities ---------------------------------------------------

@dataclass
class Options:
    club_slug: str
    groups: dict  # bundle group key -> (slug, name)
    season_start: date
    create_club_name: Optional[str] = None
    create_missing_groups: bool = False
    publish_training: bool = True


def season_of(bundle: Bundle) -> str:
    seasons = {r["source_key"].split(":")[1] for r in bundle.data["training_occurrences"]}
    if len(seasons) != 1:
        raise ImportError_("A bundle must contain exactly one training season")
    return seasons.pop()


def source_specs(bundle: Bundle, opts: Options) -> list:
    season = season_of(bundle)
    out = []
    for key in ("beginners", "advanced"):
        out.append(dict(key=key, kind="pdf_schedule", label=f"{opts.club_slug}:{season}:{key}:schedule",
                        sha256=bundle.data["sources"][key]["sha256"], ext=".pdf"))
    out.append(dict(key="workbook", kind="workbook", label=f"{opts.club_slug}:competitions-workbook",
                    sha256=bundle.data["sources"]["workbook"]["sha256"], ext=".xlsx"))
    return out


def find_source(db: Session, club_id: Optional[int], kind: str, label: str) -> Optional[CalendarSource]:
    return db.query(CalendarSource).filter(CalendarSource.kind == kind, CalendarSource.label == label,
                                           CalendarSource.club_id == club_id).order_by(CalendarSource.id).first()


def link_inventory(bundle: Bundle) -> list:
    """Unique non-WhatsApp URLs embedded in the workbook (inventory only)."""
    urls = []
    for meet in bundle.data.get("competition_candidates") or []:
        urls += [link["url"] for link in meet.get("links") or [] if link.get("url")]
    urls += [r["url"] for r in bundle.data.get("resources") or [] if r.get("url")]
    out = []
    for url in dict.fromkeys(urls):
        if is_whatsapp(url):
            continue  # private invitation: a club resource, never a source to crawl
        host = (urlparse(url).hostname or "").lower()
        kind = "federation_page" if any(host.endswith(h) for h in FEDERATION_HOSTS) else "organizer_page"
        out.append(dict(url=url[:1000], host=host, kind=kind,
                        private=any(host.endswith(h) for h in PRIVATE_HOSTS)))
    return out


def competition_key(meet: dict, taken: set) -> str:
    raw = f"{meet.get('title')}|{meet.get('location_raw')}|{meet.get('date_raw')}"
    base = f"meet:{slug(meet['title'])}:{meet.get('start_date') or 'undated'}:" \
           f"{hashlib.sha1(raw.encode()).hexdigest()[:8]}"
    key, n = base, 2
    while key in taken:  # identical duplicate rows (e.g. two undated titles)
        key, n = f"{base}#{n}", n + 1
    taken.add(key)
    return key


def resource_key(r: dict) -> str:
    return "resource:" + hashlib.sha1(f"{r.get('title')}|{r.get('url')}".encode()).hexdigest()[:16]


def edition_of(text: str) -> Optional[str]:
    match = re.search(r"\b(20\d{2}\s*[-/]\s*\d{2,4})\b", text or "")
    return match.group(1).replace(" ", "") if match else None


# --- Plan -------------------------------------------------------------------------------

def _mappings(db: Session, source: Optional[CalendarSource], target: str) -> dict:
    if source is None:
        return {}
    return {m.external_key: m for m in db.query(CalendarSourceMapping).filter(
        CalendarSourceMapping.source_id == source.id, CalendarSourceMapping.target_type == target)}


def _iso(value) -> Optional[str]:
    return value.isoformat() if value is not None else None


def build_plan(db: Session, bundle: Bundle, opts: Options) -> dict:
    validate(bundle)
    club = db.query(Club).filter(Club.slug == opts.club_slug).one_or_none()
    plan = {"parser_version": PARSER_VERSION, "bundle_sha256": bundle.sha256, "club": opts.club_slug,
            "season": season_of(bundle), "season_start": opts.season_start.isoformat(),
            "create_club": None, "create_groups": [], "groups": {}, "sources": [], "training": [], "competitions": [],
            "resources": [], "link_sources": []}
    if club is None:
        if not opts.create_club_name:
            raise ImportError_(f"Club '{opts.club_slug}' does not exist (create it, or pass --create-club NAME)")
        plan["create_club"] = {"slug": opts.club_slug, "name": opts.create_club_name}
    elif club.archived_at is not None:
        raise ImportError_("Club is archived")
    club_id = club.id if club else None

    groups = {}
    for key in sorted({r["group_key"] for r in bundle.data["training_occurrences"]}):
        if key not in opts.groups:
            raise ImportError_(f"No --group mapping for bundle group '{key}'")
        gslug, gname = opts.groups[key]
        plan["groups"][key] = gslug
        group = db.query(TrainingGroup).filter_by(club_id=club_id, slug=gslug).one_or_none() if club_id else None
        if group is None:
            if not opts.create_missing_groups:
                raise ImportError_(f"Group '{gslug}' missing (create it, or pass --create-missing-groups)")
            plan["create_groups"].append({"key": key, "slug": gslug, "name": gname})
        groups[key] = group

    sources = {}
    for spec in source_specs(bundle, opts):
        src = find_source(db, club_id, spec["kind"], spec["label"]) if club_id else None
        sources[spec["key"]] = src
        plan["sources"].append({**spec, "source_id": src.id if src else None,
                                "artifact": "unchanged" if src and src.artifact_sha256 == spec["sha256"]
                                else ("new_version" if src and src.artifact_sha256 else "new")})

    # Training occurrences (authoritative explicit dates; publish).
    for key, group in groups.items():
        src = sources[key]
        ev_maps, occ_maps = _mappings(db, src, "event"), _mappings(db, src, "occurrence")
        event_key = f"{opts.club_slug}:{plan['season']}:{key}"
        rows = sorted((r for r in bundle.data["training_occurrences"] if r["group_key"] == key),
                      key=lambda r: r["source_key"])
        ev_map = ev_maps.get(event_key)
        item = {"group": key, "event_key": event_key, "event_id": ev_map.event_id if ev_map else None,
                "create": [], "update": [], "conflict": [], "unchanged": 0, "missing_from_source": []}
        for r in rows:
            start = datetime.fromisoformat(r["start_at"]).astimezone(timezone.utc).replace(tzinfo=None)
            end = datetime.fromisoformat(r["end_at"]).astimezone(timezone.utc).replace(tzinfo=None)
            new = {"starts_at": start.isoformat(), "ends_at": end.isoformat(), "venue_name": r["venue_code"]}
            prov = {"artifact_sha256": r["source"]["sha256"], "page": r["source"]["page"],
                    "row": r["source"]["row"], "local_date": r["local_date"], "start_local": r["start_local"],
                    "end_local": r["end_local"], "timezone": r["timezone"]}
            m = occ_maps.get(r["source_key"])
            occ = db.get(EventOccurrence, m.occurrence_id) if m and m.occurrence_id else None
            if occ is None:
                if m is not None:  # mapped record was deleted locally
                    item["conflict"].append({"key": r["source_key"], "reason": "target_missing", "proposed": new})
                    continue
                item["create"].append({"key": r["source_key"], **new, "provenance": prov})
                continue
            old = {"starts_at": occ.starts_at.isoformat(), "ends_at": occ.ends_at.isoformat(),
                   "venue_name": occ.venue_name}
            if old == new:
                item["unchanged"] += 1
            elif m.locally_overridden:
                item["conflict"].append({"key": r["source_key"], "reason": "locally_overridden",
                                         "current": old, "proposed": new})
            else:
                item["update"].append({"key": r["source_key"], "occurrence_id": occ.id, "current": old, **new,
                                       "provenance": prov})
        present = {r["source_key"] for r in rows}
        item["missing_from_source"] = sorted(k for k, m in occ_maps.items()
                                             if k not in present and m.review_status != "missing_from_source")
        plan["training"].append(item)

    # Competition candidates (never published by import).
    wb = sources["workbook"]
    meet_maps, taken = _mappings(db, wb, "event"), set()
    for meet in bundle.data.get("competition_candidates") or []:
        key = competition_key(meet, taken)
        prov = {"artifact_sha256": meet["source"]["sha256"], "sheet": meet["source"]["sheet"],
                "row": meet["source"]["row"], "date_raw": meet.get("date_raw"),
                "location_raw": meet.get("location_raw"), "level_raw": meet.get("level_raw"),
                "registration_deadline_raw": meet.get("registration_deadline_raw"),
                "issue": meet.get("date_issue"),
                "links": [{"cell": link["cell"], "url": link["url"]} for link in meet.get("links") or []]}
        if meet.get("date_issue") or not meet.get("start_date"):
            disposition = "needs_review"
        elif date.fromisoformat(meet["end_date_exclusive"]) <= opts.season_start:
            disposition = "historical"
        else:
            disposition = "draft"
        m = meet_maps.get(key)
        entry = {"key": key, "title": meet["title"].strip()[:200], "disposition": disposition,
                 "start_date": meet.get("start_date"), "end_date": meet.get("end_date_exclusive"),
                 "venue": (str(meet.get("location_raw") or "").strip() or None), "provenance": prov}
        if m is None:
            entry["action"] = "create"
        elif disposition == "draft" and m.event_id:
            ev = db.get(CalendarEvent, m.event_id)
            occ = db.query(EventOccurrence).filter_by(event_id=m.event_id).first()
            same = ev is not None and occ is not None and ev.title == entry["title"] and \
                _iso(occ.start_date) == entry["start_date"] and _iso(occ.end_date) == entry["end_date"]
            if same:
                entry["action"] = "unchanged"
            elif m.locally_overridden or ev is None or ev.status != "draft":
                entry["action"] = "conflict"
            else:
                entry["action"] = "update"
                entry["event_id"] = ev.id
        elif disposition == "draft":  # reviewed item later became importable
            entry["action"] = "create"
        else:
            entry["action"] = "unchanged" if m.review_status in (disposition, "resolved") else "update"
        plan["competitions"].append(entry)

    res_maps = _mappings(db, wb, "resource")
    for r in bundle.data.get("resources") or []:
        key = resource_key(r)
        kind = "club_chat" if is_whatsapp(r.get("url")) else RESOURCE_KINDS.get(r.get("type"), "other")
        plan["resources"].append({"key": key, "label": str(r.get("title") or r.get("url"))[:200],
                                  "kind": kind, "url": r.get("url"), "edition": edition_of(r.get("title")),
                                  "action": "unchanged" if key in res_maps else "create",
                                  "provenance": {"artifact_sha256": r["source"]["sha256"],
                                                 "sheet": r["source"]["sheet"], "row": r["source"]["row"],
                                                 "type": r.get("type"), "notes": r.get("notes")}})

    existing_links = set()
    if wb is not None:
        existing_links = {s.url for s in db.query(CalendarSource).filter(CalendarSource.parent_source_id == wb.id)}
    for link in link_inventory(bundle):
        plan["link_sources"].append({**link, "action": "unchanged" if link["url"] in existing_links else "create"})
    return plan


def plan_hash(plan: dict) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True, default=str).encode()).hexdigest()


def summarize(plan: dict) -> dict:
    t = plan["training"]
    comps = plan["competitions"]
    return {
        "create_club": bool(plan["create_club"]), "create_groups": [g["slug"] for g in plan["create_groups"]],
        "training": {"create": sum(len(i["create"]) for i in t), "update": sum(len(i["update"]) for i in t),
                     "unchanged": sum(i["unchanged"] for i in t), "conflict": sum(len(i["conflict"]) for i in t),
                     "missing_from_source": sum(len(i["missing_from_source"]) for i in t)},
        "competitions": {d: sum(1 for c in comps if c["disposition"] == d) for d in
                         ("draft", "needs_review", "historical")},
        "competition_actions": {a: sum(1 for c in comps if c["action"] == a) for a in
                                ("create", "update", "unchanged", "conflict")},
        "resources": {a: sum(1 for r in plan["resources"] if r["action"] == a) for a in ("create", "unchanged")},
        "link_sources": {a: sum(1 for r in plan["link_sources"] if r["action"] == a) for a in ("create", "unchanged")},
        "artifacts": {s["key"]: s["artifact"] for s in plan["sources"]},
    }


# --- Private artifact storage -------------------------------------------------------------

def store_artifact(path: Path, sha: str, ext: str, storage_dir: Path) -> str:
    """Content-addressed private copy (0600). Returns the storage_ref."""
    target = storage_dir / sha[:2] / f"{sha}{ext}"
    storage_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = target.with_suffix(target.suffix + ".tmp")
        shutil.copyfile(path, tmp)
        os.chmod(tmp, 0o600)
        if sha256_file(tmp) != sha:
            tmp.unlink()
            raise ImportError_(f"Stored artifact hash mismatch for {path.name}")
        tmp.replace(target)
    return f"calendar-artifacts:{sha[:2]}/{sha}{ext}"


# --- Preview / apply ----------------------------------------------------------------------

def _club(db: Session, plan: dict, actor: Optional[AppUser], create: bool) -> Optional[Club]:
    club = db.query(Club).filter(Club.slug == plan["club"]).with_for_update().one_or_none()
    if club is None and create and plan["create_club"]:
        club = Club(slug=plan["club"], name=plan["create_club"]["name"], timezone="Europe/Paris",
                    created_by_user_id=actor.id if actor else None)
        db.add(club)
        db.flush()
        db.add(Calendar(kind="club", club_id=club.id, name=club.name))
        db.flush()
    return club


def _upsert_source(db: Session, club: Club, spec: dict, storage_ref: str) -> CalendarSource:
    src = find_source(db, club.id, spec["kind"], spec["label"])
    if src is None:
        src = CalendarSource(kind=spec["kind"], label=spec["label"], club_id=club.id, is_private=True)
        db.add(src)
    src.artifact_sha256, src.storage_ref = spec["sha256"], storage_ref
    db.flush()
    return src


def preview(db: Session, bundle: Bundle, opts: Options, storage_dir: Path, actor: Optional[AppUser]) -> dict:
    """Record a reviewable plan. Creates club/source METADATA only when the
    club already exists; otherwise only prints (runs need a source row)."""
    validate(bundle)
    club = db.query(Club).filter(Club.slug == opts.club_slug).one_or_none()
    if club is not None:
        # Source identity rows first (no artifact hash yet: that is set on
        # apply), so the reviewed plan equals the one apply recomputes.
        for spec in source_specs(bundle, opts):
            if find_source(db, club.id, spec["kind"], spec["label"]) is None:
                db.add(CalendarSource(kind=spec["kind"], label=spec["label"], club_id=club.id, is_private=True))
        db.commit()
    plan = build_plan(db, bundle, opts)
    digest, batch = plan_hash(plan), uuid.uuid4().hex
    refs = {}
    for spec in plan["sources"]:
        refs[spec["key"]] = store_artifact(bundle.files[spec["key"]], spec["sha256"], spec["ext"], storage_dir)
    run_ids = []
    if club is not None:
        for spec in plan["sources"]:
            src = find_source(db, club.id, spec["kind"], spec["label"])
            run = CalendarImportRun(source_id=src.id, source_sha256=spec["sha256"], parser_version=PARSER_VERSION,
                                    status="previewed", batch_id=batch, created_by_user_id=actor.id if actor else None,
                                    summary={"batch_id": batch, "plan_hash": digest, "bundle_sha256": bundle.sha256,
                                             "storage_ref": refs[spec["key"]], "counts": summarize(plan)})
            db.add(run)
            db.flush()
            run_ids.append(run.id)
        db.commit()
    # New-club previews have no persisted run rows; the reviewed plan hash
    # gates creation. Do not advertise an unusable persisted batch id.
    return {"batch_id": batch if run_ids else None, "plan_hash": digest, "runs": run_ids, "storage": refs, "summary": summarize(plan),
            "plan": plan}


def apply(db: Session, bundle: Bundle, opts: Options, storage_dir: Path, actor: Optional[AppUser],
          expected_hash: str, batch_id: Optional[str] = None) -> dict:
    # Lock before recomputing the reviewed plan, so concurrent manual edits
    # cannot be overwritten from a stale preview. Match UI event/occurrence order.
    club = db.query(Club).filter(Club.slug == opts.club_slug).with_for_update().one_or_none()
    if club is not None:
        current_source_ids = [src.id for spec in source_specs(bundle, opts)
                              if (src := find_source(db, club.id, spec["kind"], spec["label"])) is not None]
        event_keys = {f"{opts.club_slug}:{season_of(bundle)}:{r['group_key']}"
                      for r in bundle.data["training_occurrences"]}
        taken = set()
        event_keys.update(competition_key(meet, taken)
                          for meet in bundle.data.get("competition_candidates") or [])
        event_ids = db.query(CalendarSourceMapping.event_id).filter(
            CalendarSourceMapping.target_type == "event",
            CalendarSourceMapping.external_key.in_(event_keys),
            CalendarSourceMapping.source_id.in_(current_source_ids),
            CalendarSourceMapping.event_id.isnot(None))
        locked = db.query(CalendarEvent).filter(CalendarEvent.id.in_(event_ids.scalar_subquery())).order_by(
            CalendarEvent.id).with_for_update().all()
        if locked:
            db.query(EventOccurrence).filter(EventOccurrence.event_id.in_([e.id for e in locked])).order_by(
                EventOccurrence.id).with_for_update().all()
        db.expire_all()
    plan = build_plan(db, bundle, opts)
    digest = plan_hash(plan)
    if digest != expected_hash:
        raise ImportError_("The plan changed since it was previewed (source or database). Preview and review again.")
    runs = []
    if batch_id:
        source_ids = [spec["source_id"] for spec in plan["sources"]]
        runs = db.query(CalendarImportRun).filter(
            CalendarImportRun.status == "previewed", CalendarImportRun.batch_id == batch_id,
            CalendarImportRun.source_id.in_(source_ids)).order_by(CalendarImportRun.id).limit(
                len(source_ids) + 1).all()
        if len(runs) != len(source_ids) or {r.source_id for r in runs} != set(source_ids) or any(
                (r.summary or {}).get("plan_hash") != digest for r in runs):
            raise ImportError_("No previewed batch with this id and plan hash")
    try:
        result = _apply(db, plan, bundle, storage_dir, actor, runs)
        db.commit()
        return result
    except Exception:
        db.rollback()
        for run in runs:
            db.query(CalendarImportRun).filter_by(id=run.id).update({"status": "failed"})
        db.commit()
        raise


def _apply(db: Session, plan: dict, bundle: Bundle, storage_dir: Path, actor: Optional[AppUser], runs) -> dict:
    club = _club(db, plan, actor, create=True)
    now = datetime.utcnow()
    srcs, run_by_source = {}, {}
    for spec in plan["sources"]:
        ref = store_artifact(bundle.files[spec["key"]], spec["sha256"], spec["ext"], storage_dir)
        srcs[spec["key"]] = _upsert_source(db, club, spec, ref)
    for spec in plan["sources"]:
        src = srcs[spec["key"]]
        run = next((r for r in runs if r.source_id == src.id), None)
        if run is None:
            run = CalendarImportRun(source_id=src.id, source_sha256=spec["sha256"], parser_version=PARSER_VERSION,
                                    status="previewed", created_by_user_id=actor.id if actor else None,
                                    summary={"plan_hash": plan_hash(plan), "bundle_sha256": plan["bundle_sha256"],
                                             "storage_ref": src.storage_ref, "counts": summarize(plan)})
            db.add(run)
            db.flush()
        run_by_source[spec["key"]] = run
        src.last_checked_at = src.last_success_at = now

    for g in plan["create_groups"]:
        group = TrainingGroup(club_id=club.id, slug=g["slug"], name=g["name"])
        db.add(group)
        db.flush()
        db.add(Calendar(kind="group", club_id=club.id, training_group_id=group.id, name=g["name"]))
        db.flush()

    def mapping(src, target, key, **kw):
        m = db.query(CalendarSourceMapping).filter_by(source_id=src.id, target_type=target,
                                                      external_key=key).one_or_none()
        if m is None:
            m = CalendarSourceMapping(source_id=src.id, target_type=target, external_key=key)
            db.add(m)
        for k, v in kw.items():
            setattr(m, k, v)
        return m

    counts = {"occurrences_created": 0, "occurrences_updated": 0, "conflicts": 0, "missing_flagged": 0,
              "competition_drafts": 0, "review_items": 0, "resources": 0, "link_sources": 0}
    for item in plan["training"]:
        src, run = srcs[item["group"]], run_by_source[item["group"]]
        group = db.query(TrainingGroup).filter_by(club_id=club.id, slug=plan["groups"][item["group"]]).one()
        gcal = db.query(Calendar).filter_by(kind="group", training_group_id=group.id).one()
        event = db.get(CalendarEvent, item["event_id"]) if item["event_id"] else None
        if event is None:
            event = CalendarEvent(calendar_id=gcal.id, event_type="training", audience="group", status="published",
                                  title=f"Entraînement — {group.name}", timezone="Europe/Paris",
                                  created_by_user_id=actor.id if actor else None, published_at=now,
                                  description="Programme importé du planning du club. L’affectation au groupe ne "
                                              "vaut ni inscription ni présence.")
            db.add(event)
            db.flush()
            events.log_change(db, event, "imported", actor, {"title": (None, event.title)},
                              import_run_id=run.id)
            mapping(src, "event", item["event_key"], event_id=event.id, last_import_run_id=run.id,
                    provenance={"artifact_sha256": src.artifact_sha256, "group": item["group"]})
        for row in item["create"]:
            start, end = datetime.fromisoformat(row["starts_at"]), datetime.fromisoformat(row["ends_at"])
            occ = EventOccurrence(event_id=event.id, occurrence_key=row["key"], starts_at=start, ends_at=end,
                                  window_start=start, window_end=end, venue_name=row["venue_name"])
            db.add(occ)
            db.flush()
            mapping(src, "occurrence", row["key"], event_id=event.id, occurrence_id=occ.id,
                    last_import_run_id=run.id, provenance=row["provenance"], review_status=None)
            counts["occurrences_created"] += 1
        if item["create"]:
            events.log_change(db, event, "imported", actor, {"occurrences": (None, len(item["create"]))},
                              import_run_id=run.id)
        for row in item["update"]:
            occ = db.query(EventOccurrence).filter_by(id=row["occurrence_id"]).with_for_update().one()
            start, end = datetime.fromisoformat(row["starts_at"]), datetime.fromisoformat(row["ends_at"])
            changes = {}
            if (occ.starts_at, occ.ends_at) != (start, end):
                changes.update(starts_at=(occ.starts_at, start), ends_at=(occ.ends_at, end))
                occ.starts_at, occ.ends_at, occ.window_start, occ.window_end = start, end, start, end
            if occ.venue_name != row["venue_name"]:
                events.log_change(db, event, "venue_changed", actor, {"venue_name": (occ.venue_name, row["venue_name"])},
                                  occ, import_run_id=run.id)
                occ.venue_name = row["venue_name"]
            if changes:
                events.log_change(db, event, "time_changed", actor, changes, occ, import_run_id=run.id)
            occ.version += 1
            mapping(src, "occurrence", row["key"], last_import_run_id=run.id, provenance=row["provenance"])
            counts["occurrences_updated"] += 1
        for row in item["conflict"]:
            m = mapping(src, "occurrence", row["key"], review_status="conflict", last_import_run_id=run.id)
            m.provenance = {**(m.provenance or {}), "proposed": row.get("proposed"), "reason": row["reason"]}
            counts["conflicts"] += 1
        for key in item["missing_from_source"]:
            mapping(src, "occurrence", key, review_status="missing_from_source", last_import_run_id=run.id)
            counts["missing_flagged"] += 1

    wb, wb_run = srcs["workbook"], run_by_source["workbook"]
    club_cal = db.query(Calendar).filter_by(kind="club", club_id=club.id).one()
    for c in plan["competitions"]:
        if c["action"] in ("unchanged",):
            continue
        if c["action"] == "conflict":
            m = mapping(wb, "event", c["key"], review_status="conflict", last_import_run_id=wb_run.id)
            m.provenance = {**(m.provenance or {}), "proposed": {**c["provenance"], "title": c["title"],
                                                                 "start_date": c["start_date"],
                                                                 "end_date": c["end_date"]}}
            counts["conflicts"] += 1
            continue
        if c["disposition"] != "draft":
            mapping(wb, "event", c["key"], review_status=c["disposition"], last_import_run_id=wb_run.id,
                    provenance={**c["provenance"], "title": c["title"]})
            counts["review_items"] += 1
            continue
        start, end = date.fromisoformat(c["start_date"]), date.fromisoformat(c["end_date"])
        times = dict(is_all_day=True, start_date=start, end_date=end,
                     window_start=events.local_to_utc(datetime.combine(start, datetime.min.time()), "Europe/Paris"),
                     window_end=events.local_to_utc(datetime.combine(end, datetime.min.time()), "Europe/Paris"))
        description = "\n".join(line for line in (
            f"Niveau (source) : {c['provenance']['level_raw']}".strip() if c["provenance"]["level_raw"] else "",
            f"Date limite (source, non vérifiée) : {c['provenance']['registration_deadline_raw']}".strip()
            if c["provenance"]["registration_deadline_raw"] else "",
            "Candidat importé du classeur de compétitions du club — à vérifier auprès de l’organisateur avant "
            "publication.") if line)
        if c["action"] == "update":
            ev = db.query(CalendarEvent).filter_by(id=c["event_id"]).with_for_update().one()
            occ = db.query(EventOccurrence).filter_by(event_id=ev.id).one()
            ev.title, ev.venue_name, ev.version = c["title"], (c["venue"] or None) and c["venue"][:200], ev.version + 1
            for k, v in times.items():
                setattr(occ, k, v)
            occ.version += 1
            events.log_change(db, ev, "imported", actor, {"source_update": (None, c["key"])}, occ,
                              import_run_id=wb_run.id)
            mapping(wb, "event", c["key"], last_import_run_id=wb_run.id, review_status=None,
                    provenance={**c["provenance"], "title": c["title"]})
            continue
        ev = CalendarEvent(calendar_id=club_cal.id, event_type="competition", audience="club", status="draft",
                           title=c["title"], description=description,
                           venue_name=c["venue"][:200] if c["venue"] else None, timezone="Europe/Paris",
                           created_by_user_id=actor.id if actor else None)
        db.add(ev)
        db.flush()
        occ = EventOccurrence(event_id=ev.id, occurrence_key="dates", **times)
        db.add(occ)
        db.flush()
        for link in c["provenance"]["links"]:
            kind, label = LINK_COLUMNS.get(link["cell"][:1], ("other", "Lien"))
            if is_whatsapp(link["url"]):
                kind, label = "club_chat", "Groupe WhatsApp du club"
            db.add(EventResource(event_id=ev.id, kind=kind, label=label, url=link["url"][:1000],
                                 restricted_to_club=kind == "club_chat",
                                 edition_label="édition passée possible — vérifier" if kind == "results" else None))
        events.log_change(db, ev, "imported", actor, {"title": (None, ev.title)}, occ, import_run_id=wb_run.id)
        mapping(wb, "event", c["key"], event_id=ev.id, occurrence_id=occ.id, last_import_run_id=wb_run.id,
                review_status=None, provenance={**c["provenance"], "title": c["title"]})
        counts["competition_drafts"] += 1

    for r in plan["resources"]:
        if r["action"] != "create":
            continue
        res = EventResource(club_id=club.id, kind=r["kind"], label=r["label"], url=r["url"],
                            restricted_to_club=r["kind"] == "club_chat", edition_label=r["edition"])
        db.add(res)
        db.flush()
        mapping(wb, "resource", r["key"], resource_id=res.id, last_import_run_id=wb_run.id,
                provenance=r["provenance"])
        counts["resources"] += 1

    for link in plan["link_sources"]:
        if link["action"] != "create":
            continue
        db.add(CalendarSource(kind=link["kind"], label=link["host"][:200] or "link", url=link["url"],
                              club_id=club.id, parent_source_id=wb.id, is_private=link["private"]))
        counts["link_sources"] += 1

    for run in run_by_source.values():
        run.status, run.applied_at = "applied", now
        run.summary = {**(run.summary or {}), "applied": counts}
    db.flush()
    return {"club_id": club.id, "runs": [r.id for r in run_by_source.values()], "applied": counts}


def review_queue(db: Session, club_slug: str, limit: int = 100,
                 after_mapping_id: int = 0, after_draft_id: int = 0) -> list:
    """Two independently paged streams; each page contains at most 2*limit rows."""
    if not 1 <= limit <= 200 or min(after_mapping_id, after_draft_id) < 0:
        raise ImportError_("Review limit must be 1..200 and cursors nonnegative")
    club = db.query(Club).filter(Club.slug == club_slug).one_or_none()
    if club is None:
        return []
    rows = db.query(CalendarSourceMapping, CalendarSource).join(
        CalendarSource, CalendarSource.id == CalendarSourceMapping.source_id).filter(
        CalendarSource.club_id == club.id, CalendarSourceMapping.review_status.isnot(None),
        CalendarSourceMapping.review_status != "resolved", CalendarSourceMapping.id > after_mapping_id) \
        .order_by(CalendarSourceMapping.id).limit(limit).all()
    drafts = db.query(CalendarSourceMapping, CalendarEvent).join(
        CalendarEvent, CalendarEvent.id == CalendarSourceMapping.event_id).join(
        CalendarSource, CalendarSource.id == CalendarSourceMapping.source_id).filter(
        CalendarSource.club_id == club.id, CalendarEvent.status == "draft",
        CalendarSourceMapping.id > after_draft_id).order_by(CalendarSourceMapping.id).limit(limit).all()
    out = [{"queue": "mapping", "mapping_id": m.id,
            "status": m.review_status, "source": s.label, "key": m.external_key,
            "title": (m.provenance or {}).get("title"), "issue": (m.provenance or {}).get("issue"),
            "row": (m.provenance or {}).get("row")} for m, s in rows]
    out += [{"queue": "draft", "mapping_id": m.id,
             "status": "draft_unpublished", "key": m.external_key, "title": e.title, "event_id": e.id}
            for m, e in drafts]
    return out


def resolve(db: Session, club_slug: str, external_key: str, accept_source: bool) -> dict:
    """Close a review item. accept_source clears the local-override guard so
    the next reviewed import applies the source value; otherwise the local
    value is kept and the item is marked resolved."""
    club = db.query(Club).filter(Club.slug == club_slug).one_or_none()
    rows = [] if club is None else db.query(CalendarSourceMapping).join(
        CalendarSource, CalendarSource.id == CalendarSourceMapping.source_id).filter(
        CalendarSource.club_id == club.id, CalendarSourceMapping.external_key == external_key) \
        .order_by(CalendarSourceMapping.id).limit(2).all()
    if len(rows) != 1:
        raise ImportError_("No single review item with this key")
    m = rows[0]
    m.review_status = None if accept_source else "resolved"
    if accept_source:
        m.locally_overridden = False
    db.commit()
    return {"key": m.external_key, "review_status": m.review_status, "locally_overridden": m.locally_overridden}
