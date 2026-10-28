#!/usr/bin/env python3
"""Import a private review export atomically. Dry-run by default; JSON on stdin.

Run from backend: python -m scripts.migrate_sync_review < export.json
Apply only after the schema migration and deployment, with --apply.
"""
import argparse
import hashlib
import json
import sys
from sqlalchemy import select, text
from app.database import SessionLocal
from app.models.dive import Dive
from app.models.diver import Diver, DiverAlias
from app.models.dive_sync_pair import DiveSyncPair
from app.services.diver_identity import canonicalize_name, invalidate_analysis_cache
from app.services.sync_participants import caption_hash, owner_id


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def source_hash(dive):
    fields = {k: getattr(dive, k) for k in (
        'id', 'video_uuid', 'photos_asset_id', 'raw_caption', 'person_name', 'diver_id', 'dive_datetime')}
    fields['dive_datetime'] = dive.dive_datetime.strftime('%Y-%m-%dT%H:%M:%S')
    return hashlib.sha256(canonical_json(fields)).hexdigest()


def migrate(db, document):
    if document.get('schema') != 'dive-sync-partner-review/v1':
        raise ValueError('Unsupported review schema')
    primary = db.get(Diver, document.get('primary_diver_id'))
    if not primary or not primary.is_primary_user or not primary.active:
        raise ValueError('Primary diver mismatch')
    if db.bind.dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(7264931)'))
    ids = [i['dive_id'] for i in document['items']]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate dive IDs')
    report = {'applied': 0, 'already_applied': 0, 'skipped': [], 'created_profiles': [], 'includes_primary': 0}
    for item in document['items']:
        decision = item.get('decision') or {}
        if decision.get('status') != 'validated':
            report['skipped'].append(item['dive_id'])
            continue
        provenance = decision.get('provenance', {})
        if provenance.get('human_reviewed') is not True or not decision.get('event_id'):
            raise ValueError(f"Missing review evidence: {item['dive_id']}")
        dive = db.execute(select(Dive).where(Dive.id == item['dive_id']).with_for_update()).scalar_one()
        pair = db.get(DiveSyncPair, dive.id)
        event_id = decision['event_id']
        if pair and pair.source == 'reviewed':
            if pair.evidence.get('event_id') != event_id:
                raise ValueError(f'Existing different review: {dive.id}')
            report['already_applied'] += 1
            continue
        source = item['source']
        expected = decision['decided_against_source_snapshot_sha256']
        if (not dive.is_sync or source_hash(dive) != expected
                or source.get('source_snapshot_sha256') != expected
                or caption_hash(dive.raw_caption) != source.get('caption_sha256')):
            raise ValueError(f'Stale review/source identity: {dive.id}; re-review before applying')
        participants = decision.get('participants', [])
        if len(participants) != 2:
            raise ValueError(f'Invalid pair: {dive.id}')
        chosen = []
        for participant in participants:
            if participant.get('unknown') is True:
                chosen.append(None)
            elif participant.get('diver_id'):
                diver = db.get(Diver, participant['diver_id'])
                if diver is None or not diver.active:
                    raise ValueError(f'Inactive/missing participant: {dive.id}')
                chosen.append(diver.id)
            elif participant.get('new_name'):
                name = participant['new_name'].strip()
                canonical = canonicalize_name(name)
                if not 1 < len(name) <= 100:
                    raise ValueError('Invalid new name')
                matches = db.execute(select(Diver).outerjoin(DiverAlias).where(
                    (Diver.canonical_name == canonical) | (DiverAlias.canonical_alias == canonical))).scalars().unique().all()
                if len(matches) > 1 or (matches and not matches[0].active):
                    raise ValueError(f'Ambiguous/retired new name: {name}')
                if matches:
                    diver = matches[0]
                else:
                    diver = Diver(display_name=name, canonical_name=canonical)
                    db.add(diver)
                    db.flush()
                    report['created_profiles'].append(name)
                chosen.append(diver.id)
            else:
                raise ValueError('Invalid participant')
        if chosen[0] is not None and chosen[0] == chosen[1]:
            raise ValueError('Duplicate participant')
        if not any(chosen):
            raise ValueError('Both participants unknown')
        if pair is None:
            pair = DiveSyncPair(dive_id=dive.id)
            db.add(pair)
        pair.first_diver_id, pair.second_diver_id = chosen
        pair.source = 'reviewed'
        pair.complete = all(chosen)
        pair.conflict = False
        pair.caption_sha256 = pair.latest_caption_sha256 = caption_hash(dive.raw_caption)
        pair.evidence = {'event_id': event_id, 'decided_at': decision.get('decided_at'),
                         'source_snapshot_sha256': expected, 'provenance': provenance,
                         'participants': participants}
        dive.diver_id = owner_id(db, pair)
        report['applied'] += 1
        report['includes_primary'] += primary.id in chosen
    invalidate_analysis_cache(db)
    db.flush()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    document = json.load(sys.stdin)
    with SessionLocal() as db:
        try:
            report = migrate(db, document)
            if args.apply:
                db.commit()
            else:
                db.rollback()
            print(json.dumps({'mode': 'apply' if args.apply else 'dry-run', **report}, ensure_ascii=False))
        except Exception:
            db.rollback()
            raise


if __name__ == '__main__':
    main()
