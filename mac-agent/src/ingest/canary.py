"""P2 DEV canary runner (media-backbone).

Drives ONE real clip through the verified-ingest flow:

  Ready-album discovery -> exact caption (stable provider + shadow parity)
  -> targeted materialization (Photos edited rendition) -> content hash
  -> private B2 DEV upload -> full-GET roundtrip verification
  -> operator-tunneled verified DB commit (receipt-confirmed)
  -> local cleanup.

Execution modes:
  discover    list `DiveAnalyzer Ready` album assets (safe provenance only)
  run         drive ObjectStoreIngestCoordinator for exactly one asset
  journal     print a redacted state-journal summary
  b2-preflight  synthetic-object PUT/HEAD/GET/presign against the DEV bucket
  privacy-probe anonymous (credential-less) list/GET denial evidence
  presign-test  short-TTL presigned GET (200) + byte-range GET (206) evidence

Privacy doctrine: this runner NEVER prints caption text, credentials, or
presigned URLs; identity evidence is limited to hashes, lengths and states.
The per-clip evidence file (0600) may contain the shadow caption because the
server commit needs it; it never leaves the private state dir except through
the server commit service.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .caption import (
    CaptionResult,
    CurrentStableCaptionProvider,
    PhotosDbCaptionProviderShadow,
    compare_caption_providers,
)
from .coordinator import (
    INGEST_IMPL_VERSION,
    RENDITION_SEMANTICS,
    InjectedCrash,
    ObjectStoreIngestCoordinator,
)
from .content_addr import sha256_file
from .errors import ObjectStoreUnavailable
from .objectstore.b2 import B2Config, BackblazeB2Store
from .state_store import IngestStateStore

READY_ALBUM_TITLES = (
    "DiveAnalyzer Ready",
    "DiveAnalyser Ready",
)
ENV_FILE_MAX_MODE = 0o600


def find_ready_album(db):
    """Return (title, album_info) for the canary boundary album, or (None, None).

    Accepts the packet's en-US spelling and the project's canonical en-GB
    spelling ('Dive Analyser'); the exact matched title is always recorded in
    evidence so the boundary is unambiguous.
    """
    by_title = {ai.title: ai for ai in db.album_info}
    for title in READY_ALBUM_TITLES:
        if title in by_title:
            return title, by_title[title]
    return None, None


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_canary_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    for section in ("photos", "object_store", "materializer"):
        if section not in cfg or not isinstance(cfg[section], dict):
            raise SystemExit(f"canary config missing section: {section}")
    return cfg


def load_env_file(path: str) -> dict[str, str]:
    env_path = Path(path).expanduser()
    mode = env_path.stat().st_mode & 0o777
    if mode & 0o077:
        raise SystemExit(
            f"refusing env file {env_path}: mode {oct(mode)} must be 0600 or stricter"
        )
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"malformed env line in {env_path}")
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    required = ("B2_APPLICATION_KEY_ID", "B2_APPLICATION_KEY")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise SystemExit(f"env file missing required keys: {missing}")
    return values


def get_photos_db(library_path: str):
    import osxphotos

    return osxphotos.PhotosDB(str(library_path))


def caption_sha(raw: str | None) -> str | None:
    if raw is None:
        return None
    import hashlib

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_stable_provider(library_path: str) -> CurrentStableCaptionProvider:
    def describe(video_uuid: str) -> str | None:
        db = get_photos_db(library_path)
        matches = db.photos(uuid=[video_uuid])
        return matches[0].description if matches else None

    return CurrentStableCaptionProvider(describe)


def edit_fingerprint(photo) -> str:
    import hashlib

    material = json.dumps(
        {
            "hasadjustments": bool(getattr(photo, "hasadjustments", False)),
            "duration": photo.duration,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def photo_provenance(photo) -> dict:
    return {
        "uuid": photo.uuid,
        "original_filename": photo.original_filename,
        "duration_seconds": round(photo.duration or 0.0, 3),
        "hasadjustments": bool(getattr(photo, "hasadjustments", False)),
        "ismissing": bool(getattr(photo, "ismissing", False)),
        "incloud": bool(getattr(photo, "incloud", False)),
        "favorited": bool(getattr(photo, "favorite", False)),
        "date": str(photo.date) if photo.date else None,
        "edited_provenance": "PHOTOS_EDITED_RENDITION_CANDIDATE",
    }


def mode_discover(cfg: dict) -> int:
    db = get_photos_db(cfg["photos"]["library_path"])
    title, album = find_ready_album(db)
    if album is None:
        print(f"ready_album_found 0 titles={list(READY_ALBUM_TITLES)}")
        return 1
    assets = [p for p in album.photos if p.ismovie]
    print(f"ready_album_found {len(assets)} title={title}")
    for photo in assets:
        raw = photo.description
        print(
            json.dumps(
                {
                    **photo_provenance(photo),
                    "caption_present": bool(raw),
                    "caption_sha256": caption_sha(raw),
                    "caption_length": len(raw) if raw is not None else None,
                    "caption_utf8_bytes": len(raw.encode("utf-8")) if raw else 0,
                    "edit_fingerprint": edit_fingerprint(photo),
                }
            )
        )
    return 0


def make_materialize_fn(cfg: dict):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from media_materializer import MediaMaterializer

    mat_cfg = cfg["materializer"]
    osxphotos_path = mat_cfg.get("osxphotos_path") or "osxphotos"

    def materialize(video_uuid: str, workdir: Path) -> Path:
        materializer = MediaMaterializer(
            materialization_dir=str(workdir),
            max_bytes=int(mat_cfg.get("max_bytes", 2_000_000_000)),
            osxphotos_path=osxphotos_path,
            export_timeout_seconds=int(mat_cfg.get("export_timeout_seconds", 900)),
            use_photokit=False,
        )
        return asyncio.run(materializer.materialize(video_uuid))

    return materialize


def ffprobe_metadata(path: Path, ffprobe_bin: str) -> dict:
    proc = subprocess.run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise SystemExit(f"ffprobe failed: {proc.stderr[-400:]}")
    data = json.loads(proc.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    fmt = data.get("format", {})
    return {
        "codec": video.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "duration_seconds": float(fmt["duration"]) if fmt.get("duration") else None,
        "container": fmt.get("format_name"),
        "bit_rate": int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
        "start_pts": video.get("start_pts"),
        "start_time": video.get("start_time"),
        "nb_frames": video.get("nb_frames"),
    }


def parse_caption_metadata(raw: str) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from metadata import parse_dive_caption

    parsed = parse_dive_caption(raw)
    if parsed is None:
        return {"parser": "legacy_parse_dive_caption_v1", "result": None}
    return {
        "parser": "legacy_parse_dive_caption_v1",
        "result": {
            key: getattr(parsed, key)
            for key in (
                "dive_code",
                "height",
                "phase1_performance",
                "phase2_performance",
                "is_sync",
                "is_smack",
                "person_name",
            )
            if hasattr(parsed, key)
        },
    }


def build_b2_store(cfg: dict, env: dict[str, str] | None):
    os_cfg = cfg["object_store"]
    credentials = env or {}
    if credentials:
        os.environ.setdefault("B2_APPLICATION_KEY_ID", credentials["B2_APPLICATION_KEY_ID"])
        os.environ.setdefault("B2_APPLICATION_KEY", credentials["B2_APPLICATION_KEY"])
    config = B2Config(
        environment=os_cfg.get("environment", "dev"),
        bucket=os_cfg["bucket"],
        region=os_cfg.get("region") or None,
        endpoint_url=os_cfg.get("endpoint_url") or None,
        prefix=os_cfg.get("prefix", "blobs/sha256"),
        presign_ttl_seconds=int(os_cfg.get("presign_ttl_seconds", 300)),
        max_retries=int(os_cfg.get("max_retries", 3)),
    )
    return BackblazeB2Store(config), config


def make_commit_db_fn(receipt_path: str | None):
    if receipt_path is None:
        def commit_db_fn(payload):
            raise ObjectStoreUnavailable(
                "db_commit_transport_unavailable: canary commits are tunneled by the "
                "operator through the server commit service; pass --commit-receipt "
                "once the verified commit receipt exists"
            )

        return commit_db_fn

    def commit_db_fn(payload):
        receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
        if receipt.get("input", {}).get("payload") != payload:
            raise ObjectStoreUnavailable(
                "commit receipt does not match the staged coordinator payload; "
                "refusing to mark DB_COMMITTED"
            )
        if not receipt.get("result", {}).get("blob_sha256"):
            raise ObjectStoreUnavailable("commit receipt missing server result rows")
        return receipt["result"]

    return commit_db_fn


def journal_summary(state_store: IngestStateStore) -> dict:
    doc = json.loads(json.dumps(state_store.doc))
    caption = doc.get("caption") or {}
    if caption.get("raw") is not None:
        caption["raw_utf8_bytes"] = len(caption["raw"].encode("utf-8"))
        caption["raw"] = f"<redacted sha256={caption.get('sha256')}>"
    doc["caption"] = caption
    return doc


def _update_evidence(state_dir: Path, video_uuid: str, updater) -> None:
    evidence_path = state_dir / f"{video_uuid}.evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    updater(evidence)
    fd = os.open(evidence_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(evidence, fh, ensure_ascii=False, indent=2, sort_keys=True)


def stage_commit_document(cfg: dict, video_uuid: str) -> dict:
    os_cfg = cfg["object_store"]
    state_dir = Path(os_cfg["state_dir"]).expanduser()
    state_store = IngestStateStore(state_dir / f"{video_uuid}.json")
    state_store.load(video_uuid)
    doc = state_store.doc
    if not (doc.get("remote") or {}).get("verified"):
        raise SystemExit("refusing to stage commit: journal is not REMOTE_VERIFIED")
    media = doc["media"]
    caption = doc["caption"]
    payload = {
        "video_uuid": video_uuid,
        "ingest_impl_version": INGEST_IMPL_VERSION,
        "rendition_semantics": RENDITION_SEMANTICS,
        "caption": {
            "raw": caption["raw"],
            "sha256": caption["sha256"],
            "provider": caption["provider"],
        },
        "blob": {
            "sha256": media["sha256"],
            "byte_size": media["byte_size"],
            "object_key": media["object_key"],
            "storage_backend": os_cfg.get("storage_backend", "b2"),
            "bucket": os_cfg["bucket"],
        },
        "remote_verified": bool((doc.get("remote") or {}).get("verified")),
    }
    evidence_path = state_dir / f"{video_uuid}.evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    media_meta = evidence.get("media_metadata") or {}
    extra = {
        "environment": os_cfg.get("environment", "dev"),
        "codec": media_meta.get("codec"),
        "width": media_meta.get("width"),
        "height": media_meta.get("height"),
        "duration_seconds": media_meta.get("duration_seconds"),
        "photos_edit_fingerprint": evidence.get("edit_fingerprint"),
        "source_provenance": {
            "photos_asset_uuid": (evidence.get("photo") or {}).get("uuid"),
            "original_filename": (evidence.get("photo") or {}).get("original_filename"),
            "rendition_semantics": evidence.get("rendition_semantics"),
            "hasadjustments": (evidence.get("photo") or {}).get("hasadjustments"),
            "photos_duration_seconds": (evidence.get("photo") or {}).get(
                "duration_seconds"
            ),
            "materialized_duration_seconds": media_meta.get("duration_seconds"),
            "duration_match": evidence.get("rendition_duration_match"),
            "captured_at": evidence.get("captured_at"),
        },
        "shadow_provider": (evidence.get("shadow") or {}).get("provider"),
        "shadow_raw": (evidence.get("shadow") or {}).get("shadow_raw"),
        "shadow_sha256": (evidence.get("shadow") or {}).get("shadow_sha256"),
        "shadow_available": (evidence.get("shadow") or {}).get("available"),
        "parser_version": (evidence.get("parsed") or {}).get("parser"),
        "parsed_json": (evidence.get("parsed") or {}).get("result"),
    }
    return {"payload": payload, "extra": extra}


def mode_caption_mutation(args) -> int:
    """Caption-only mutation: same media/blob, new CaptionRevision.

    Gate: the Photos edit fingerprint MUST be unchanged (the user edited only
    the caption). If the fingerprint changed, media changed too and a full
    re-ingest (new blob) is required instead.
    """
    cfg = load_canary_config(args.config)
    os_cfg = cfg["object_store"]
    state_dir = Path(os_cfg["state_dir"]).expanduser()
    state_store = IngestStateStore(state_dir / f"{args.video_uuid}.json")
    state_store.load(args.video_uuid)
    doc = state_store.doc
    media = doc.get("media") or {}
    if not media.get("sha256"):
        raise SystemExit("no committed media in journal; run the full canary first")

    evidence = json.loads(
        (state_dir / f"{args.video_uuid}.evidence.json").read_text(encoding="utf-8")
    )
    library_path = cfg["photos"]["library_path"]
    db = get_photos_db(library_path)
    matches = db.photos(uuid=[args.video_uuid])
    if not matches:
        raise SystemExit(f"asset not found: {args.video_uuid}")
    photo = matches[0]
    new_fingerprint = edit_fingerprint(photo)
    if new_fingerprint != evidence.get("edit_fingerprint"):
        print(
            json.dumps(
                {
                    "mode": "caption-mutation",
                    "outcome": "refused_media_changed",
                    "fingerprint_before": evidence.get("edit_fingerprint"),
                    "fingerprint_after": new_fingerprint,
                }
            )
        )
        return 2

    stable = build_stable_provider(library_path)
    stable_result = stable.get_caption(args.video_uuid)
    if not stable_result.available:
        raise SystemExit(f"caption unavailable: {stable_result.error}")
    if stable_result.sha256 == (doc.get("caption") or {}).get("sha256"):
        print(
            json.dumps(
                {
                    "mode": "caption-mutation",
                    "outcome": "unchanged_caption",
                    "caption_sha256": stable_result.sha256,
                }
            )
        )
        return 1

    shadow = PhotosDbCaptionProviderShadow(library_path)
    shadow_result = shadow.get_caption(args.video_uuid)
    parity = compare_caption_providers([(args.video_uuid, stable_result, shadow_result)])
    media_meta = evidence.get("media_metadata") or {}
    document = {
        "payload": {
            "video_uuid": args.video_uuid,
            "ingest_impl_version": INGEST_IMPL_VERSION,
            "rendition_semantics": RENDITION_SEMANTICS,
            "caption": {
                "raw": stable_result.raw,
                "sha256": stable_result.sha256,
                "provider": stable_result.provider,
            },
            "blob": {
                "sha256": media["sha256"],
                "byte_size": media["byte_size"],
                "object_key": media["object_key"],
                "storage_backend": os_cfg.get("storage_backend", "b2"),
                "bucket": os_cfg["bucket"],
            },
            "remote_verified": True,
        },
        "extra": {
            "environment": os_cfg.get("environment", "dev"),
            "codec": media_meta.get("codec"),
            "width": media_meta.get("width"),
            "height": media_meta.get("height"),
            "duration_seconds": media_meta.get("duration_seconds"),
            "photos_edit_fingerprint": new_fingerprint,
            "shadow_provider": shadow_result.provider,
            "shadow_raw": shadow_result.raw,
            "shadow_sha256": shadow_result.sha256,
            "shadow_available": shadow_result.available,
            "parser_version": (parse_caption_metadata(stable_result.raw or "")).get("parser"),
            "parsed_json": (parse_caption_metadata(stable_result.raw or "")).get("result"),
            "mutation_kind": "caption_only",
        },
    }
    _update_evidence(
        state_dir,
        args.video_uuid,
        lambda ev: ev.update(
            {
                "edit_fingerprint": new_fingerprint,
                "caption": {
                    "provider": stable_result.provider,
                    "available": True,
                    "caption_sha256": stable_result.sha256,
                    "caption_length": len(stable_result.raw or ""),
                    "caption_utf8_bytes": len((stable_result.raw or "").encode("utf-8")),
                    "caption_raw": stable_result.raw,
                },
                "shadow": {
                    "provider": shadow_result.provider,
                    "available": shadow_result.available,
                    "shadow_sha256": shadow_result.sha256,
                    "shadow_length": len(shadow_result.raw or ""),
                    "shadow_raw": shadow_result.raw,
                    "error_family": shadow_result.error_family,
                },
                "parity": parity,
                "mutation": {
                    "kind": "caption_only",
                    "captured_at": utcnow(),
                    "previous_caption_sha256": (doc.get("caption") or {}).get("sha256"),
                },
            }
        ),
    )
    print(json.dumps(document, ensure_ascii=False))
    return 0


def mode_staged_payload(args) -> int:
    cfg = load_canary_config(args.config)
    document = stage_commit_document(cfg, args.video_uuid)
    print(json.dumps(document, ensure_ascii=False))
    return 0


def mode_run(args) -> int:
    cfg = load_canary_config(args.config)
    env = load_env_file(args.env_file) if args.env_file else None
    os_cfg = cfg["object_store"]
    state_dir = Path(os_cfg["state_dir"]).expanduser()
    temp_root = Path(os_cfg["temp_root"]).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    library_path = cfg["photos"]["library_path"]
    stable = build_stable_provider(library_path)
    shadow = PhotosDbCaptionProviderShadow(library_path)
    store, b2_config = build_b2_store(cfg, env)
    raw_materialize_fn = make_materialize_fn(cfg)

    def materialize_fn(video_uuid: str, workdir: Path) -> Path:
        started_at = utcnow()
        path = raw_materialize_fn(video_uuid, workdir)
        finished_at = utcnow()
        media_meta = ffprobe_metadata(path, cfg["ffprobe_path"])
        _update_evidence(
            state_dir,
            video_uuid,
            lambda ev: ev.update(
                {
                    "materialization": {
                        "started_at": started_at,
                        "finished_at": finished_at,
                        "byte_size": path.stat().st_size,
                    },
                    "media_metadata": media_meta,
                    "rendition_duration_match": abs(
                        (media_meta.get("duration_seconds") or 0.0)
                        - ((ev.get("photo") or {}).get("duration_seconds") or 0.0)
                    )
                    <= 0.2,
                }
            ),
        )
        return path

    commit_db_fn = make_commit_db_fn(args.commit_receipt)

    state_store = IngestStateStore(state_dir / f"{args.video_uuid}.json")
    failpoints = {}
    if args.crash_before_commit:
        failpoints["REMOTE_VERIFIED:before_effect"] = "raise"

    # Pre-capture photo provenance + shadow parity evidence (read-only).
    evidence_path = state_dir / f"{args.video_uuid}.evidence.json"
    if not evidence_path.exists() or args.refresh_evidence:
        db = get_photos_db(library_path)
        matches = db.photos(uuid=[args.video_uuid])
        if not matches:
            raise SystemExit(f"asset not found in Photos library: {args.video_uuid}")
        photo = matches[0]
        stable_result = stable.get_caption(args.video_uuid)
        shadow_result = shadow.get_caption(args.video_uuid)
        parity = compare_caption_providers([(args.video_uuid, stable_result, shadow_result)])
        evidence = {
            "captured_at": utcnow(),
            "ready_album_title": find_ready_album(db)[0],
            "photo": photo_provenance(photo),
            "edit_fingerprint": edit_fingerprint(photo),
            "caption": {
                "provider": stable_result.provider,
                "available": stable_result.available,
                "caption_sha256": stable_result.sha256,
                "caption_length": len(stable_result.raw) if stable_result.raw else 0,
                "caption_utf8_bytes": len(stable_result.raw.encode("utf-8"))
                if stable_result.raw
                else 0,
                "caption_raw": stable_result.raw,
            },
            "shadow": {
                "provider": shadow_result.provider,
                "available": shadow_result.available,
                "shadow_sha256": shadow_result.sha256,
                "shadow_length": len(shadow_result.raw) if shadow_result.raw else 0,
                "shadow_raw": shadow_result.raw,
                "error_family": shadow_result.error_family,
            },
            "parity": parity,
            "parsed": parse_caption_metadata(stable_result.raw or ""),
            "rendition_semantics": "photos_edited_rendition",
        }
        fd = os.open(evidence_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(evidence, fh, ensure_ascii=False, indent=2, sort_keys=True)

    coordinator = ObjectStoreIngestCoordinator(
        video_uuid=args.video_uuid,
        state_store=state_store,
        object_store=store,
        materialize_fn=materialize_fn,
        commit_db_fn=commit_db_fn,
        temp_root=temp_root,
        caption_provider=stable,
        min_free_disk_bytes=int(os_cfg.get("min_free_disk_bytes", 0)),
        failpoints=failpoints,
        storage_backend=os_cfg.get("storage_backend", "b2"),
        bucket=b2_config.bucket,
    )
    started = time.time()
    try:
        final_state = coordinator.run_once()
    except InjectedCrash as crash:
        doc = state_store.doc
        print(
            json.dumps(
                {
                    "mode": "run",
                    "outcome": "controlled_crash",
                    "failpoint": str(crash),
                    "state": doc["state"],
                    "remote_verified": bool((doc.get("remote") or {}).get("verified")),
                    "db_commit_committed": bool((doc.get("db_commit") or {}).get("committed")),
                    "object_key": (doc.get("media") or {}).get("object_key"),
                    "media_sha256": (doc.get("media") or {}).get("sha256"),
                    "elapsed_seconds": round(time.time() - started, 2),
                }
            )
        )
        return 0
    doc = state_store.doc
    print(
        json.dumps(
            {
                "mode": "run",
                "outcome": "converged",
                "final_state": str(final_state),
                "state": doc["state"],
                "media_sha256": (doc.get("media") or {}).get("sha256"),
                "object_key": (doc.get("media") or {}).get("object_key"),
                "remote_verified": bool((doc.get("remote") or {}).get("verified")),
                "db_commit_committed": bool((doc.get("db_commit") or {}).get("committed")),
                "media_cleaned": bool(doc.get("media_cleaned", False)),
                "attempts": doc.get("attempts", 0),
                "last_error": doc.get("last_error"),
                "elapsed_seconds": round(time.time() - started, 2),
            }
        )
    )
    return 0 if final_state.is_terminal and str(final_state) != "IngestState.QUARANTINED" else 2


def mode_journal(args) -> int:
    cfg = load_canary_config(args.config)
    os_cfg = cfg["object_store"]
    state_dir = Path(os_cfg["state_dir"]).expanduser()
    state_store = IngestStateStore(state_dir / f"{args.video_uuid}.json")
    state_store.load(args.video_uuid)
    print(json.dumps(journal_summary(state_store), ensure_ascii=False, indent=2))
    return 0


def mode_b2_preflight(args) -> int:
    cfg = load_canary_config(args.config)
    env = load_env_file(args.env_file)
    store, b2_config = build_b2_store(cfg, env)
    probe_sha = sha256_file(Path(__file__))
    key = f"{b2_config.prefix}/preflight/canary-preflight-{probe_sha[:12]}.bin"
    payload = b"diveseen-backbone-p2-preflight\n" * 16
    started = time.time()
    put = store.put(key, payload)
    head = store.head(key)
    fetched = store.get(key)
    url = store.presign_get(key, ttl_seconds=120)
    result = {
        "mode": "b2-preflight",
        "endpoint": b2_config.endpoint_url,
        "region": b2_config.region,
        "bucket": b2_config.bucket,
        "object_key": key,
        "put_sha256": put.sha256,
        "put_bytes": put.byte_size,
        "head_found": head is not None,
        "head_bytes": head.byte_size if head else None,
        "get_sha256_matches_put": sha256_bytes_hex(fetched) == put.sha256,
        "get_bytes": len(fetched),
        "presign_generated": bool(url),
        "presign_url_logged": False,
        "elapsed_seconds": round(time.time() - started, 2),
    }
    store.delete_object_explicit_operator_action(key)
    result["synthetic_probe_deleted"] = store.head(key) is None
    print(json.dumps(result))
    return 0


def sha256_bytes_hex(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _anonymous_probe(url: str, expect_codes: tuple[int, ...]) -> dict:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            return {"url_kind": url.split("/")[3] if "/" in url else url, "status": resp.status}
    except urllib.error.HTTPError as exc:
        return {
            "url_kind": "bucket_list" if "list-type" in url else "object_get",
            "status": exc.code,
            "denied": exc.code in expect_codes,
            "error_class": exc.reason.__class__.__name__ if exc.reason else None,
        }


def mode_privacy_probe(args) -> int:
    cfg = load_canary_config(args.config)
    os_cfg = cfg["object_store"]
    endpoint = (os_cfg.get("endpoint_url") or f"https://s3.{os_cfg['region']}.backblazeb2.com").rstrip("/")
    bucket = os_cfg["bucket"]
    list_url = f"{endpoint}/{bucket}?list-type=2&max-keys=1"
    get_url = f"{endpoint}/{bucket}/{args.key}"
    results = [_anonymous_probe(list_url, (403,)), _anonymous_probe(get_url, (403,))]
    for probe in results:
        probe["url_redacted"] = True
    print(json.dumps({"mode": "privacy-probe", "probes": results}))
    return 0


def mode_presign_test(args) -> int:
    cfg = load_canary_config(args.config)
    env = load_env_file(args.env_file)
    store, b2_config = build_b2_store(cfg, env)
    head = store.head(args.key)
    if head is None:
        raise SystemExit(f"object absent: {args.key}")
    url = store.presign_get(args.key, ttl_seconds=args.ttl)
    started = time.time()
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=60) as resp:
        body = resp.read()
        full_status = resp.status
        full_len = len(body)
    range_request = urllib.request.Request(url, headers={"Range": f"bytes=0-1023"})
    with urllib.request.urlopen(range_request, timeout=60) as resp:
        ranged = resp.read()
        range_status = resp.status
        content_range = resp.headers.get("Content-Range")
    print(
        json.dumps(
            {
                "mode": "presign-test",
                "ttl_seconds": args.ttl,
                "presign_generated": True,
                "presign_url_logged": False,
                "head_bytes": head.byte_size,
                "full_get_status": full_status,
                "full_get_bytes": full_len,
                "range_request": "bytes=0-1023",
                "range_status": range_status,
                "content_range": content_range,
                "range_bytes": len(ranged),
                "elapsed_seconds": round(time.time() - started, 2),
            }
        )
    )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="media-backbone P2 DEV canary")
    parser.add_argument("mode", choices=[
        "discover",
        "run",
        "journal",
        "staged-payload",
        "caption-mutation",
        "b2-preflight",
        "privacy-probe",
        "presign-test",
    ])
    parser.add_argument("--config", required=True)
    parser.add_argument("--env-file")
    parser.add_argument("--video-uuid")
    parser.add_argument("--key", help="object key (privacy-probe / presign-test)")
    parser.add_argument("--crash-before-commit", action="store_true")
    parser.add_argument("--commit-receipt")
    parser.add_argument("--refresh-evidence", action="store_true")
    parser.add_argument("--ttl", type=int, default=300)
    args = parser.parse_args(argv)

    if args.mode == "discover":
        return mode_discover(load_canary_config(args.config))
    if args.mode == "run":
        if not args.video_uuid:
            raise SystemExit("run requires --video-uuid")
        return mode_run(args)
    if args.mode == "journal":
        if not args.video_uuid:
            raise SystemExit("journal requires --video-uuid")
        return mode_journal(args)
    if args.mode == "staged-payload":
        if not args.video_uuid:
            raise SystemExit("staged-payload requires --video-uuid")
        return mode_staged_payload(args)
    if args.mode == "caption-mutation":
        if not args.video_uuid:
            raise SystemExit("caption-mutation requires --video-uuid")
        return mode_caption_mutation(args)
    if args.mode == "b2-preflight":
        return mode_b2_preflight(args)
    if args.mode == "privacy-probe":
        if not args.key:
            raise SystemExit("privacy-probe requires --key")
        return mode_privacy_probe(args)
    if args.mode == "presign-test":
        if not args.key:
            raise SystemExit("presign-test requires --key")
        return mode_presign_test(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
