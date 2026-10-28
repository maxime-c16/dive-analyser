import pytest
from app.models.diver import Diver
from app.models.dive_sync_pair import DiveSyncPair
from app.services.sync_participants import caption_names, proposal, update_from_caption, caption_hash
from scripts.migrate_sync_review import migrate, source_hash


@pytest.fixture
def people(test_db):
    divers = [Diver(display_name=n, canonical_name=n.lower(), is_primary_user=n == 'Maxime')
              for n in ['Maxime', 'Mat', 'Sara']]
    test_db.add_all(divers)
    test_db.flush()
    return divers


def test_caption_convention(test_db, people):
    me, mat, sara = people
    assert proposal(test_db, '103B G 3m SYNC Mat') == (me.id, mat.id, True)
    assert proposal(test_db, '103B G 3m Mat SYNC') == (me.id, mat.id, True)
    assert proposal(test_db, '103B G 3m SYNC Mat+Sara') == (mat.id, sara.id, True)
    assert proposal(test_db, '103B G 3m SYNC') == (me.id, None, False)
    assert not proposal(test_db, '103B G 3m Mat Sara SYNC')[2]
    assert not proposal(test_db, '103B G 3m SYNC Mat+Mat')[2]
    assert not proposal(test_db, '103B G 3m SYNC Unknown')[2]


def test_unrecognized_annotations_never_silently_choose_pair(test_db, people):
    assert proposal(test_db, '103B G 3m PBSR6 Mat SYNC') == (None, None, False)


def test_review_survives_mac_replay_and_contradictory_caption(test_db, sample_dive, people):
    db, dive = test_db, sample_dive
    me, mat, sara = people
    original = '103B G 3m SYNC Mat'
    pair = DiveSyncPair(dive_id=dive.id, first_diver_id=me.id, second_diver_id=sara.id,
                        source='reviewed', complete=True, conflict=False,
                        caption_sha256=caption_hash(original), latest_caption_sha256=caption_hash(original))
    db.add(pair)
    db.flush()
    for incoming, conflict in [(original, False), ('103B P 3m SYNC Sara', False),
                               ('103B P 3m SYNC Mat', True), ('103B P 3m', True)]:
        dive.diver_id = mat.id
        dive.is_sync = False
        update_from_caption(db, dive, incoming)
        assert dive.diver_id == me.id and dive.is_sync
        assert pair.second_diver_id == sara.id and pair.conflict is conflict


def document(dive, participants):
    fingerprint = source_hash(dive)
    return {'schema': 'dive-sync-partner-review/v1', 'primary_diver_id': participants[0]['diver_id'],
            'items': [{'dive_id': dive.id, 'source': {'source_snapshot_sha256': fingerprint,
                        'caption_sha256': caption_hash(dive.raw_caption)},
                       'decision': {'event_id': 'test-event', 'status': 'validated',
                                    'decided_against_source_snapshot_sha256': fingerprint,
                                    'participants': participants, 'provenance': {'human_reviewed': True}}}]}


def test_migration_is_reviewed_idempotent_and_protects_new_profile(test_db, sample_dive, people):
    dive = sample_dive
    dive.is_sync, dive.diver_id, dive.raw_caption = True, people[0].id, '103B G 3m SYNC'
    doc = document(dive, [{'diver_id': people[0].id}, {'new_name': 'CLARA'}])
    assert migrate(test_db, doc)['applied'] == 1
    assert migrate(test_db, doc)['already_applied'] == 1
    pair = test_db.get(DiveSyncPair, dive.id)
    assert pair.source == 'reviewed' and pair.complete
    update_from_caption(test_db, dive, dive.raw_caption)
    assert pair.complete and not pair.conflict


def test_stale_review_refused(test_db, sample_dive, people):
    dive = sample_dive
    dive.is_sync = True
    doc = document(dive, [{'diver_id': people[0].id}, {'unknown': True}])
    dive.raw_caption = 'changed'
    with pytest.raises(ValueError, match='Stale'):
        migrate(test_db, doc)


def test_machine_upsert_uses_pair_and_cannot_erase_review(api_client, test_db, auth_headers, people):
    from app.models.dive import Dive
    me, mat, sara = people
    body = {'video_uuid': 'sync-participants-test-video-1234567890', 'date': '2026-10-28T12:00:00',
            'dive_code': '103B', 'height': '3m', 'performance': 'G', 'is_sync': True,
            'person_name': 'Mat', 'raw_caption': '103B G 3m SYNC Mat'}
    response = api_client.post('/api/v1/videos/sync', json=body, headers=auth_headers)
    assert response.status_code == 201, response.text
    dive = test_db.query(Dive).filter_by(video_uuid=body['video_uuid']).one()
    pair = test_db.get(DiveSyncPair, dive.id)
    assert dive.diver_id == me.id and pair.second_diver_id == mat.id
    pair.source = 'reviewed'
    pair.second_diver_id = sara.id
    test_db.commit()
    response = api_client.post('/api/v1/videos/sync', json=body, headers=auth_headers)
    assert response.status_code == 201, response.text
    test_db.refresh(pair)
    assert pair.second_diver_id == sara.id and not pair.conflict
    body.update(is_sync=False, raw_caption='103B P 3m Mat', performance='P')
    response = api_client.post('/api/v1/videos/sync', json=body, headers=auth_headers)
    assert response.status_code == 201, response.text
    test_db.refresh(pair)
    test_db.refresh(dive)
    assert dive.is_sync and dive.diver_id == me.id and dive.performance == 'P'
    assert pair.second_diver_id == sara.id and pair.conflict


def test_identity_lookup_is_sql_bounded_after_alias_deduplication(test_db, people):
    from sqlalchemy import event
    from app.models.diver import DiverAlias
    from app.services.sync_participants import exact_diver, matching_diver_ids
    mat = people[1]
    test_db.add_all(DiverAlias(diver_id=mat.id, alias=f'Alias {i}', canonical_alias=f'alias-{i}')
                    for i in range(200))
    # Canonical and alias can point to different identities: do not silently pick.
    test_db.add(DiverAlias(diver_id=people[2].id, alias='Mat', canonical_alias='mat'))
    test_db.flush()
    statements = []
    def record(connection, cursor, statement, parameters, context, executemany):
        if 'JOIN diver_aliases' in statement:
            statements.append(statement)
    event.listen(test_db.bind, 'before_cursor_execute', record)
    try:
        assert set(matching_diver_ids(test_db, 'mat')) == {mat.id, people[2].id}
        assert exact_diver(test_db, 'Mat').id == mat.id
        assert exact_diver(test_db, 'MAT') is None
        assert len(statements) >= 3
        assert all('SELECT DISTINCT divers.id' in sql and 'LIMIT' in sql for sql in statements)
    finally:
        event.remove(test_db.bind, 'before_cursor_execute', record)
