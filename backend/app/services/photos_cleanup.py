"""Read-only, fail-closed eligibility check for Mac Photos cleanup."""
import hashlib

from sqlalchemy import or_

from app.models.dive import Dive
from app.models.diver import Diver, DiverAlias
from app.models.photos_asset import PhotosAsset, PhotosAssetAgentIdentity
from app.models.media_backbone import MediaBlob, MediaRevision, CaptionRevision, IngestObjectState
from app.services.diver_identity import canonicalize_name
from app.services.media_backbone import trusted_prod_location


def check_cleanup(db, request, prod_bucket):
    def refuse(reason):
        return {"eligible": False, "reason": reason}

    keeper = db.get(Diver, request.keeper_diver_id)
    if keeper is None or not keeper.active or not keeper.is_primary_user:
        return refuse("keeper_not_primary")
    asset = db.query(PhotosAsset).filter_by(video_uuid=request.video_uuid).one_or_none()
    if asset is None:
        return refuse("asset_unknown")
    identity = db.query(PhotosAssetAgentIdentity).filter_by(
        photos_asset_id=asset.id, agent_id=request.agent_id,
        local_uuid=request.photos_uuid).one_or_none()
    if identity is None:
        return refuse("local_identity_unconfirmed")
    dives = db.query(Dive).filter(or_(Dive.photos_asset_id == asset.id,
                                    Dive.video_uuid == request.video_uuid)).limit(2).all()
    if len(dives) != 1:
        return refuse("ambiguous_dive")
    dive = dives[0]
    pair_revision = None
    if dive.is_lineup:
        return refuse("person_not_exclusive")
    if dive.is_sync:
        from app.models.dive_sync_pair import DiveSyncPair
        from app.services.sync_participants import pair_fingerprint
        pair = db.get(DiveSyncPair, dive.id)
        if pair is None or not pair.complete or pair.conflict:
            return refuse("person_not_exclusive")
        ids = {pair.first_diver_id, pair.second_diver_id}
        if keeper.id in ids or None in ids:
            return refuse("kept_or_unknown_diver")
        participants = db.query(Diver).filter(Diver.id.in_(ids), Diver.active.is_(True)).all()
        if len(participants) != 2 or any(p.is_primary_user for p in participants):
            return refuse("kept_or_unknown_diver")
        pair_revision = pair_fingerprint(pair)
        # Old workers cannot authorize sync removal. New workers pin this value
        # when enqueuing a NEW continuous ingest, never during historical review.
        if not getattr(request, 'sync_pair_check', False):
            return refuse("person_not_exclusive")
        if getattr(request, 'pair_revision', None) != pair_revision:
            return {"eligible": False, "reason": "pair_revision_changed", "pair_revision": pair_revision}
        diver = participants[0]
    else:
        if not (dive.person_name or "").strip():
            return refuse("person_not_exclusive")
        diver = db.get(Diver, dive.diver_id) if dive.diver_id else None
        if diver is None or not diver.active or diver.is_primary_user or diver.id == keeper.id:
            return refuse("kept_or_unknown_diver")
        name = canonicalize_name(dive.person_name)
        matches = db.query(Diver.id).outerjoin(DiverAlias).filter(
            or_(Diver.canonical_name == name, DiverAlias.canonical_alias == name)).distinct().limit(2).all()
        if {diver_id for (diver_id,) in matches} != {diver.id}:
            return refuse("ambiguous_person")
    if hashlib.sha256((dive.raw_caption or "").encode()).hexdigest() != request.caption_sha256:
        return refuse("metadata_changed")
    revision = db.query(MediaRevision).filter_by(video_uuid=request.video_uuid).order_by(
        MediaRevision.observed_at.desc(), MediaRevision.id.desc()).first()
    caption = db.query(CaptionRevision).filter_by(video_uuid=request.video_uuid).order_by(
        CaptionRevision.observed_at.desc(), CaptionRevision.id.desc()).first()
    if (revision is None or revision.blob_sha256 != request.blob_sha256
            or revision.photos_edit_fingerprint != request.edit_fingerprint
            or revision.rendition_semantics != "photos_edited_rendition"
            or (revision.source_provenance or {}).get("photos_asset_uuid", "").upper() != request.photos_uuid.upper()
            or caption is None or caption.caption_sha256 != request.caption_sha256):
        return refuse("revision_changed_or_missing")
    blob = db.get(MediaBlob, request.blob_sha256)
    location, denial = trusted_prod_location(db, request.blob_sha256, prod_bucket)
    ledger = db.query(IngestObjectState).filter_by(
        video_uuid=request.video_uuid, blob_sha256=request.blob_sha256,
        caption_sha256=request.caption_sha256, environment="prod", verified=True,
        state="DB_COMMITTED").first()
    if blob is None or blob.byte_size != request.byte_size or denial or ledger is None:
        return refuse("durable_backup_unconfirmed")
    if location.object_key != request.object_key or location.bucket != request.bucket:
        return refuse("backup_location_changed")
    return {"eligible": True, "pair_revision": pair_revision, "reason": "verified_other_diver",
            "diver_id": diver.id, "video_uuid": request.video_uuid,
            "photos_uuid": request.photos_uuid, "blob_sha256": request.blob_sha256}
