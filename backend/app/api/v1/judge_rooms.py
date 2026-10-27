"""Room-only capabilities. Public clips only; no workspace token is minted."""

import json
import logging
import secrets
import time
from pathlib import Path
from threading import RLock
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import get_db
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.session import Session as TrainingSession
from app.models.dd_lookup import DDLookup
from app.models.fina_dive_code import FINADiveCode
from app.models.photos_asset import PhotosAsset
from app.models.media import MediaCacheEntry
from app.models.matchmaking import AutomaticRating
from app.models.evaluation import EvaluationRequest, EvaluationRating
from app.models.judge_room import (
    JudgeRoomResult,
    JudgeRoomRating,
    JudgeShadowPreference,
)
from app.services.judge_room import Room, rooms, playback_duration
from app.services.dive_access import owned_diver_ids
from app.services.write_guard import optional_session_user
from app.api.v1.dive_sharing import same_origin, secure_headers
from app.api.v1.media import _serve_media_file, _web_preview_entry
from app.services.signed_media import signed_url
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rooms")
lock = RLock()


class Join(BaseModel):
    nickname: str = Field(default="Guest", min_length=1, max_length=40)


class Action(BaseModel):
    action: str
    mode: str = "classic"
    source: str = "community"
    code: str = Field(default="", max_length=10)
    score: int | None = Field(default=None, ge=0, le=20, strict=True)
    suspect: str | None = None
    choice: str | None = Field(default=None, max_length=10)


def room_for(code):
    room = rooms.get(code)
    if room is None or time.time() - room.touched > 6 * 3600:
        rooms.pop(code, None)
        raise HTTPException(404, "Room expired")
    return room


def player_for(room, request):
    token = request.cookies.get("jr_" + room.code, "")
    key = room.tokens.get(token)
    if key is None:
        raise HTTPException(403, "Join this room first")
    return key


def media_entries(db, dive):
    return (
        db.query(MediaCacheEntry)
        .join(PhotosAsset, MediaCacheEntry.photos_asset_id == PhotosAsset.id)
        .filter(
            PhotosAsset.video_uuid == dive.video_uuid, MediaCacheEntry.status == "ready"
        )
        .order_by(MediaCacheEntry.id.desc())
        .all()
    )


def playlist(db, room, user, source, code=""):
    query = db.query(Dive).filter(
        Dive.visibility == "public",
        Dive.diver_id.is_not(None),
        Dive.video_uuid.is_not(None),
    )
    if source == "latest":
        ids = owned_diver_ids(db, user.id)
        latest = (
            db.query(Dive)
            .join(TrainingSession, TrainingSession.id == Dive.session_id)
            .filter(Dive.diver_id.in_(ids))
            .order_by(TrainingSession.date.desc(), Dive.id.desc())
            .first()
        )
        if latest is None:
            return []
        query = query.filter(
            Dive.session_id == latest.session_id, Dive.diver_id.in_(ids)
        )
    if source == "code":
        query = query.filter(Dive.dive_code == code)
    from app.services.judge_room import GHOSTS

    preference = db.get(JudgeShadowPreference, 1)
    shadow_enabled = bool(preference and preference.enabled) and room.mode != "code"
    room.ghosts = (
        [dict(id="shadow", name="Fantôme de Maxime", emoji="🌑", points=0)]
        if shadow_enabled
        else []
    ) + [dict(id=k, name=n, emoji=e, points=0) for k, n, e, _ in GHOSTS]
    offsets = []
    if shadow_enabled:
        # One grouped query for peer averages: the previous per-rating query
        # ran up to 1,000 extra queries per room configuration.
        mine = {
            r.dive_id: r.score_half_steps
            for r in db.query(AutomaticRating)
            .filter_by(evaluator_user_id=1)
            .limit(1000)
        }
        peer_avg = (
            dict(
                db.query(
                    AutomaticRating.dive_id,
                    func.avg(AutomaticRating.score_half_steps),
                )
                .filter(
                    AutomaticRating.evaluator_user_id != 1,
                    AutomaticRating.dive_id.in_(mine),
                )
                .group_by(AutomaticRating.dive_id)
                .all()
            )
            if mine
            else {}
        )
        for dive_id, score in mine.items():
            avg = peer_avg.get(dive_id)
            if avg is not None:
                offsets.append(score - float(avg))
    # Batch-fetch everything the loop below needs: room creation used to run
    # media, asset, rating, shadow-rating and ownership lookups per candidate
    # dive (up to 160 candidates). Ownership is loop-invariant; hoist it.
    owned = owned_diver_ids(db, user.id)
    candidates = query.order_by(Dive.id.desc()).limit(160).all()
    uuids = [d.video_uuid for d in candidates]
    dive_ids = [d.id for d in candidates]
    by_uuid = {}
    if uuids:
        for video_uuid, entry in (
            db.query(PhotosAsset.video_uuid, MediaCacheEntry)
            .join(PhotosAsset, MediaCacheEntry.photos_asset_id == PhotosAsset.id)
            .filter(
                PhotosAsset.video_uuid.in_(uuids),
                MediaCacheEntry.status == "ready",
            )
            .order_by(MediaCacheEntry.id.desc())
            .all()
        ):
            by_uuid.setdefault(video_uuid, []).append(entry)
    assets = {}
    if uuids:
        for a in (
            db.query(PhotosAsset)
            .filter(PhotosAsset.video_uuid.in_(uuids))
            .order_by(PhotosAsset.id)
            .all()
        ):
            assets.setdefault(a.video_uuid, a)
    stored_auto: dict[int, list] = {}
    if room.mode != "code" and dive_ids:
        for r in (
            db.query(AutomaticRating)
            .filter(AutomaticRating.dive_id.in_(dive_ids))
            .all()
        ):
            stored_auto.setdefault(r.dive_id, []).append((f"a{r.id}", r.score_half_steps))
    stored_eval: dict[int, list] = {}
    if room.mode != "code" and dive_ids:
        for dive_id, r in (
            db.query(EvaluationRequest.dive_id, EvaluationRating)
            .join(EvaluationRequest, EvaluationRequest.id == EvaluationRating.request_id)
            .filter(EvaluationRequest.dive_id.in_(dive_ids))
            .all()
        ):
            stored_eval.setdefault(dive_id, []).append(
                (f"e{r.id}", r.score_half_steps)
            )
    stored_room: dict[int, list] = {}
    if room.mode != "code" and dive_ids:
        for r in (
            db.query(JudgeRoomRating)
            .filter(JudgeRoomRating.dive_id.in_(dive_ids))
            .all()
        ):
            stored_room.setdefault(r.dive_id, []).append((f"r{r.id}", r.score_half_steps))
    shadow_auto: dict[int, object] = {}
    shadow_eval: dict[int, object] = {}
    if shadow_enabled and dive_ids:
        for r in (
            db.query(AutomaticRating)
            .filter(
                AutomaticRating.dive_id.in_(dive_ids),
                AutomaticRating.evaluator_user_id == 1,
            )
            .all()
        ):
            shadow_auto.setdefault(r.dive_id, r)
        for dive_id, r in (
            db.query(EvaluationRequest.dive_id, EvaluationRating)
            .join(EvaluationRequest, EvaluationRequest.id == EvaluationRating.request_id)
            .filter(
                EvaluationRequest.dive_id.in_(dive_ids),
                EvaluationRating.evaluator_user_id == 1,
            )
            .all()
        ):
            shadow_eval.setdefault(dive_id, r)
    divers = (
        {d.id: d.display_name for d in db.query(Diver).filter(Diver.id.in_(
            {d.diver_id for d in candidates}
        )).all()}
        if candidates
        else {}
    )
    result = []
    for dive in candidates:
        choices = []
        if room.mode == "code":
            candidates = [
                c
                for (c,) in db.query(DDLookup.dive_code)
                .join(FINADiveCode, FINADiveCode.dive_code == DDLookup.dive_code)
                .filter(
                    DDLookup.height == dive.height,
                    DDLookup.platform_type == dive.platform_type,
                    FINADiveCode.group == int(dive.dive_code[0]),
                    DDLookup.dive_code != dive.dive_code,
                )
                .distinct()
                .order_by(DDLookup.dive_code)
            ]
            if len(candidates) < 3:
                continue
            from app.services.judge_room import seeded

            rng = seeded(room.code, dive.id)
            choices = [dive.dive_code] + rng.sample(candidates, 3)
            rng.shuffle(choices)
        entries = [
            e for e in by_uuid.get(dive.video_uuid, []) if Path(e.storage_path).is_file()
        ]
        video = _web_preview_entry(entries)
        if video is None:
            continue
        asset = assets.get(dive.video_uuid)
        stored = []
        if room.mode != "code":
            stored = (
                stored_auto.get(dive.id, [])
                + stored_eval.get(dive.id, [])
                + stored_room.get(dive.id, [])
            )
        shadow_rating = shadow_auto.get(dive.id) if shadow_enabled else None
        if shadow_enabled and shadow_rating is None:
            shadow_rating = shadow_eval.get(dive.id)
        result.append(
            dict(
                choices=choices,
                host_owned=dive.diver_id in owned,
                shadow_comment=shadow_rating.comment if shadow_rating else None,
                shadow_score=shadow_rating.score_half_steps if shadow_rating else None,
                shadow_offset=sum(offsets) / len(offsets) if offsets else 0,
                id=dive.id,
                diver_name=divers[dive.diver_id],
                dive_code=dive.dive_code,
                height=dive.height,
                dd=float(dive.official_dd) if dive.official_dd else None,
                duration=playback_duration(
                    video.storage_path,
                    video.duration_seconds
                    or (asset.duration_seconds if asset else None)
                    or 10,
                ),
                poster_url=f"/api/v1/rooms/{room.code}/media/{dive.id}/poster",
                playback_url=f"/api/v1/rooms/{room.code}/media/{dive.id}/video",
                stored=stored,
            )
        )
        if len(result) == 8:
            break
    return result


def join(room, payload, request, response, db):
    existing = room.tokens.get(request.cookies.get("jr_" + room.code, ""))
    user = optional_session_user(request, db)
    key = f"u{user.id}" if user else existing or "g" + secrets.token_hex(12)
    if key not in room.players:
        if room.phase != "lobby" or len(room.players) >= 8:
            raise HTTPException(409, "Room full or already started")
        from app.services.member_avatar import avatar_identity

        room.players[key] = dict(
            avatar_url=avatar_identity(user)["avatar_url"] if user else None,
            id=key,
            user_id=user.id if user else None,
            name=user.display_name if user else payload.nickname.strip() or "Guest",
            points=0,
            streak=0,
        )
    token = (
        request.cookies.get("jr_" + room.code)
        if existing == key
        else secrets.token_urlsafe(32)
    )
    room.tokens = {t: k for t, k in room.tokens.items() if k != key}
    room.tokens[token] = key
    response.set_cookie(
        "jr_" + room.code,
        token,
        httponly=True,
        # Uvicorn sees http behind the HTTPS proxy, so derive Secure from
        # configuration (AUTH_COOKIE_SECURE=false for plain-HTTP local tests).
        secure=get_settings().auth_cookie_secure,
        samesite="strict",
        max_age=21600,
        path="/api/v1/rooms/" + room.code,
    )
    secure_headers(response)
    return room.snapshot(key, time.time())


class ShadowInput(BaseModel):
    enabled: bool


@router.get("/preferences/shadow")
def shadow_preference(request: Request, db: Session = Depends(get_db)):
    user = optional_session_user(request, db)
    if user is None:
        raise HTTPException(401, "Sign in")
    row = db.get(JudgeShadowPreference, user.id)
    return dict(enabled=bool(row and row.enabled))


@router.post("/preferences/shadow", dependencies=[Depends(same_origin)])
def set_shadow_preference(
    payload: ShadowInput, request: Request, db: Session = Depends(get_db)
):
    user = optional_session_user(request, db)
    if user is None:
        raise HTTPException(401, "Sign in")
    row = db.get(JudgeShadowPreference, user.id)
    if row is None:
        row = JudgeShadowPreference(user_id=user.id)
        db.add(row)
    row.enabled = int(payload.enabled)
    db.commit()
    return dict(enabled=payload.enabled)


@router.post("", dependencies=[Depends(same_origin)])
def create(
    payload: Join, request: Request, response: Response, db: Session = Depends(get_db)
):
    user = optional_session_user(request, db)
    if user is None:
        raise HTTPException(401, "Sign in to create a room")
    with lock:
        for code, old in list(rooms.items()):
            if time.time() - old.touched > 21600:
                del rooms[code]
        if len(rooms) >= 500:
            raise HTTPException(503, "Too many rooms")
        code = "".join(
            secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(4)
        )
        while code in rooms:
            code = "".join(
                secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(4)
            )
        room = Room(code, f"u{user.id}")
        room.playlist = playlist(db, room, user, "community")
        rooms[code] = room
        return join(room, payload, request, response, db)


@router.get("/{code}/invite")
def invite(code: str, response: Response):
    with lock:
        room = room_for(code)
        secure_headers(response)
        return dict(
            code=room.code,
            host=room.players[room.host]["name"],
            count=len(room.players),
            mode=room.mode,
            dives=len(room.playlist),
            posters=[
                f'/api/v1/rooms/{code}/invite-poster/{d["id"]}'
                for d in room.playlist[:3]
            ],
        )


@router.get("/{code}/invite-poster/{dive_id}")
def invite_poster(
    code: str, dive_id: int, request: Request, db: Session = Depends(get_db)
):
    with lock:
        room = room_for(code)
        if dive_id not in [d["id"] for d in room.playlist]:
            raise HTTPException(404, "Not in playlist")
    return room_media_response(dive_id, "poster", request, db)


@router.post("/{code}/join", dependencies=[Depends(same_origin)])
def enter(
    code: str,
    payload: Join,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    with lock:
        return join(room_for(code), payload, request, response, db)


def tick(room, db):
    room.advance(time.time())
    if room.phase == "results" and not room.persisted:
        row = db.get(JudgeRoomResult, room.game_id)
        if row:
            row.result = json.dumps(dict(players=room.players, mole=room.mole))
            db.commit()
            room.persisted = True


@router.get("/{code}")
def state(
    code: str, request: Request, response: Response, db: Session = Depends(get_db)
):
    with lock:
        room = room_for(code)
        key = player_for(room, request)
        tick(room, db)
        secure_headers(response)
        return room.snapshot(key, time.time())


@router.post("/{code}/actions", dependencies=[Depends(same_origin)])
def act(
    code: str,
    payload: Action,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    with lock:
        room = room_for(code)
        key = player_for(room, request)
        tick(room, db)
        if payload.action in ("configure", "start", "replay"):
            if key != room.host:
                raise HTTPException(403, "Host only")
            user = optional_session_user(request, db)
            if user is None or key != f"u{user.id}":
                raise HTTPException(401, "Host session expired")
            if payload.action == "replay":
                if room.phase != "results":
                    raise HTTPException(409, "Game not finished")
                room.persisted = False
                room.phase = "lobby"
                room.index = 0
                room.results = []
                room.ballots = {}
                room.mole = None
                room.game_id = secrets.token_hex(16)
                room.reset_scores()
            elif room.phase != "lobby":
                raise HTTPException(409, "Game already started")
            elif payload.action == "configure":
                if payload.mode not in (
                    "classic",
                    "mole",
                    "code",
                ) or payload.source not in (
                    "latest",
                    "community",
                    "code",
                ):
                    raise HTTPException(422, "Unknown mode or source")
                room.mode = payload.mode
                room.source = payload.source
                room.playlist = playlist(db, room, user, payload.source, payload.code)
            else:
                # Recheck public visibility and media at start, never trust the lobby snapshot.
                for dive in room.playlist:
                    row = db.get(Dive, dive["id"])
                    if row is None or row.visibility != "public":
                        raise HTTPException(409, "Playlist visibility changed")
                if not room.playlist:
                    raise HTTPException(422, "No playable public dives")
                db.add(JudgeRoomResult(id=room.game_id, code=room.code, mode=room.mode))
                db.commit()
                room.assign_mole()
                room.start(time.time())
        elif payload.action == "score":
            now = time.time()
            if (
                room.mode == "code"
                or room.phase != "judge"
                or now < room.starts
                or now >= room.closes
                or payload.score is None
                or key in room.votes
            ):
                raise HTTPException(409, "Scoring closed or already submitted")
            dive = room.playlist[room.index]
            p = room.players[key]
            db.add(
                JudgeRoomRating(
                    room_id=room.game_id,
                    dive_id=dive["id"],
                    player_id=key,
                    user_id=p["user_id"],
                    nickname=p["name"][:40],
                    score_half_steps=payload.score,
                    dive_code=dive["dive_code"],
                    height=dive["height"],
                )
            )
            db.commit()
            room.votes[key] = payload.score
            tick(room, db)
        elif payload.action == "answer":
            now = time.time()
            if (
                room.mode != "code"
                or room.phase != "judge"
                or now < room.starts
                or now >= room.closes
                or key in room.votes
                or payload.choice not in room.playlist[room.index]["choices"]
            ):
                raise HTTPException(409, "Answer closed or invalid")
            room.votes[key] = payload.choice
            room.answer_times[key] = now - room.scoring_starts
            tick(room, db)
        elif payload.action == "vote":
            if room.phase != "mole" or (
                payload.suspect is not None
                and payload.suspect not in [p["id"] for p in room.panel()]
            ):
                raise HTTPException(409, "Invalid ballot")
            room.ballots.setdefault(key, payload.suspect)
            tick(room, db)
        elif payload.action == "next":
            if room.phase != "reveal":
                raise HTTPException(409, "Nothing to skip")
            room.skips.add(key)
            tick(room, db)
        else:
            raise HTTPException(422, "Unknown action")
        secure_headers(response)
        return room.snapshot(key, time.time())


def light_redirect(db, dive):
    """The Library's "Léger" derivative (720p short side) straight from B2.

    Room membership was checked by the caller, so this signs the object
    directly instead of going through the session-only revision route.
    Any missing proof or provider error falls back to the cached preview.
    """
    from app.api.v1.media_playback import (
        _flags_enabled,
        _has_current_derivative_proof,
        _resolve_verified_prod_location,
    )
    from app.models.media_backbone import MediaRevision
    from app.services import b2_presign
    from app.services.derivative_read import safe_resolve_clip_derivatives

    if not _flags_enabled() or not dive.video_uuid:
        return None
    try:
        clip = safe_resolve_clip_derivatives(db, dive.video_uuid)
        light = clip and clip.roles.get("light")
        if light is None or light.state != "ready" or not light.playback_url:
            return None
        revision = db.get(MediaRevision, int(light.playback_url.split("/")[-2]))
        if revision is None or not _has_current_derivative_proof(db, revision):
            return None
        location, _ = _resolve_verified_prod_location(db, revision)
        if location is None:
            return None
        bucket, key, location_id = location.bucket, location.object_key, location.id
        db.rollback()  # never hold a transaction over provider I/O
        url = b2_presign.presign_get(
            bucket=bucket, object_key=key, storage_location_id=location_id
        ).url
    except Exception:
        logger.warning("Room light derivative unavailable", exc_info=True)
        return None
    response = RedirectResponse(url, status_code=302)
    secure_headers(response)
    return response


def room_media_response(dive_id, kind, request, db):
    # Deliberately outside the room lock: no SQL, stat, signing or byte I/O
    # may serialize the room's sockets or other participants' media requests.
    dive = db.get(Dive, dive_id)
    if dive is None or dive.visibility != "public":
        raise HTTPException(404, "Video no longer public")
    if kind == "video" and request.query_params.get("q") != "preview":
        light = light_redirect(db, dive)
        if light is not None:
            return light
    entries = [e for e in media_entries(db, dive) if Path(e.storage_path).is_file()]
    entry = (
        next((e for e in entries if e.rendition == "poster"), None)
        if kind == "poster"
        else _web_preview_entry(entries) if kind == "video" else None
    )
    if entry is None:
        raise HTTPException(404, "Media unavailable")
    url = signed_url(entry.storage_path, entry.checksum_sha256, ttl_seconds=120)
    if url:
        response = RedirectResponse(url, status_code=302)
        secure_headers(response)  # authorization redirect is never cached
        return response
    # Direct uvicorn development / unsigned installations retain the same
    # scoped Range transport. nginx installations use signed URLs above.
    response = _serve_media_file(
        Path(entry.storage_path),
        entry.content_type or ("image/jpeg" if kind == "poster" else "video/mp4"),
        request,
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@router.get("/{code}/media/{dive_id}/{kind}")
def media(
    code: str, dive_id: int, kind: str, request: Request, db: Session = Depends(get_db)
):
    with lock:
        room = room_for(code)
        player_for(room, request)
        if dive_id not in [d["id"] for d in room.playlist]:
            raise HTTPException(404, "Not in this playlist")
    return room_media_response(dive_id, kind, request, db)


# Same room cookie boundary as HTTP. A reconnect receives the current snapshot,
# including the authoritative start deadline, never a stream of playback commands.
from fastapi import WebSocket, WebSocketDisconnect
from app.database import SessionLocal
from starlette.concurrency import run_in_threadpool
import asyncio


@router.websocket("/{code}/live")
async def live(websocket: WebSocket, code: str):
    from app.api.v1.auth import _origin_allowed

    if not _origin_allowed(websocket):
        await websocket.close(code=1008)
        return
    try:
        with lock:
            room = room_for(code)
            key = player_for(room, websocket)
    except HTTPException:
        await websocket.close(code=1008)
        return
    connection_id = secrets.token_hex(12)
    with lock:
        room.connections[connection_id] = key
    await websocket.accept()

    def snapshot():
        with lock, SessionLocal() as db:
            room = room_for(code)
            tick(room, db)
            return room.snapshot(key, time.time())

    try:
        while True:
            await websocket.send_json(await run_in_threadpool(snapshot))
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=0.25)
                if isinstance(message, dict) and message.get("type") in (
                    "ready",
                    "ended",
                ):
                    with lock:
                        room_for(code).signal(
                            key,
                            message["type"],
                            message.get("index"),
                            message.get("game_id"),
                            time.time(),
                        )
            except asyncio.TimeoutError:
                pass
    except (WebSocketDisconnect, RuntimeError, HTTPException, ValueError):
        return
    finally:
        with lock:
            room.connections.pop(connection_id, None)
