"""Caption proposals never overwrite a human-reviewed synchro pair."""
import hashlib
import re
from sqlalchemy import or_, select
from app.models.diver import Diver, DiverAlias
from app.models.dive_sync_pair import DiveSyncPair
from app.services.diver_identity import canonicalize_name, get_primary_diver


def caption_hash(caption):
    return hashlib.sha256((caption or '').encode()).hexdigest()


def caption_names(caption):
    """Strict grammar: one name implies primary; plus-separated names are explicit.

    Unknown annotations/multiple bare names fail closed rather than dropping names.
    """
    tokens = (caption or '').split()
    sync = any(t.upper() in ('SYNC', 'SYNCHRO') for t in tokens)
    if not sync:
        return None
    names = []
    invalid = False
    for token in tokens[1:]:
        upper = token.upper()
        if upper in {'SYNC', 'SYNCHRO', 'SMACK', 'BELLY', 'RIP', 'SD', 'DB', 'HU'}:
            continue
        if re.fullmatch(r'(?:[FBMGP0-4])(?:/[FBMGP0-4])?', upper):
            continue
        if re.fullmatch(r'(?:1|3|5|7|7\.5|10)m[p]?', token, re.I):
            continue
        parts = token.split('+')
        if len(parts) > 2 or any(not re.fullmatch(r"[^\W\d_][^\W\d_'-]*(?:['-][^\W\d_]+)*", p, re.UNICODE) for p in parts):
            invalid = True
        elif names:
            invalid = True
        else:
            names = parts
    return {'names': names, 'valid': not invalid}


def matching_diver_ids(db, name, *, active_only=False, spelling=None):
    """Bound at SQL level, after deduplicating aliases, including ambiguity."""
    canonical = canonicalize_name(name)
    statement = select(Diver.id).outerjoin(DiverAlias).where(or_(
        Diver.canonical_name == canonical, DiverAlias.canonical_alias == canonical))
    if active_only:
        statement = statement.where(Diver.active.is_(True))
    if spelling is not None:
        statement = statement.where(Diver.display_name == spelling)
    return db.execute(statement.distinct().limit(2)).scalars().all()


def exact_diver(db, name):
    """Prefer unique exact spelling; case-folded duplicate identities stay ambiguous."""
    ids = matching_diver_ids(db, name, active_only=True)
    if len(ids) != 1:
        ids = matching_diver_ids(db, name, active_only=True, spelling=name)
    return db.get(Diver, ids[0]) if len(ids) == 1 else None


def proposal(db, caption):
    parsed = caption_names(caption)
    if parsed is None:
        return None
    primary = get_primary_diver(db)
    if not parsed['valid']:
        return (None, None, False)
    names = parsed['names']
    if len(names) == 0:
        return (primary.id, None, False)
    divers = [exact_diver(db, n) for n in names]
    ids = ([primary.id] if len(names) == 1 else []) + [d.id if d else None for d in divers]
    complete = all(ids) and len(set(ids)) == 2
    if ids[0] == ids[1] and ids[0] is not None:
        return (ids[0], None, False)
    return (*ids, bool(complete))


def owner_id(db, pair):
    ids = [i for i in (pair.first_diver_id, pair.second_diver_id) if i]
    primary = get_primary_diver(db).id
    return primary if primary in ids else (ids[0] if ids else None)


def update_from_caption(db, dive, raw_caption):
    pair = db.get(DiveSyncPair, dive.id)
    digest = caption_hash(raw_caption)
    if pair and pair.source == 'reviewed':
        # Replaying the source used during review is expected, not a conflict.
        # Later contradictory/unresolvable captions require explicit resolution.
        incoming = proposal(db, raw_caption)
        same = incoming is not None and incoming[2] and pair.complete and {
            incoming[0], incoming[1]} == {pair.first_diver_id, pair.second_diver_id}
        pair.latest_caption_sha256 = digest
        pair.conflict = digest != pair.caption_sha256 and not same
        dive.is_sync = True
        dive.diver_id = owner_id(db, pair)
        return pair
    if not dive.is_sync:
        if pair:
            db.delete(pair)
        return None
    incoming = proposal(db, raw_caption)
    first, second, complete = incoming or (None, None, False)
    if pair is None:
        pair = DiveSyncPair(dive_id=dive.id, source='caption')
        db.add(pair)
    pair.first_diver_id, pair.second_diver_id, pair.complete = first, second, complete
    pair.conflict = False
    pair.caption_sha256 = pair.latest_caption_sha256 = digest
    pair.evidence = {'parser': 'sync-pair-v1'}
    dive.diver_id = owner_id(db, pair)
    return pair


def pair_fingerprint(pair):
    value = f'{pair.first_diver_id}:{pair.second_diver_id}:{pair.source}:{pair.complete}:{pair.conflict}:{pair.caption_sha256}:{pair.latest_caption_sha256}:{pair.updated_at.isoformat() if pair.updated_at else ""}'
    return hashlib.sha256(value.encode()).hexdigest()
