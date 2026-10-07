"""Opt-in PostgreSQL migration/concurrency smoke check on a disposable database.

Run with MATCHMAKING_TEST_DATABASE_URL pointing to a database whose name starts
with matchmaking_test_. Never accepts a production database. CI's portable
suite uses SQLite; this check covers SQL window ranking and advisory locking.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path


def main():
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker
    url = make_url(os.environ['MATCHMAKING_TEST_DATABASE_URL'])
    assert url.database.startswith('matchmaking_test_'), 'Disposable test database required'
    os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)
    from app.main import app  # register the same complete mapper set as production
    from app.database import Base
    from app.models.dive import Dive
    from app.models.diver import Diver
    from app.models.session import Session as TrainingSession
    from app.models.user_auth import AppUser, UserDiverAccess
    from app.models.photos_asset import PhotosAsset
    from app.models.media import MediaCacheEntry
    from app.models.matchmaking import ReviewStackItem
    from app.services import matchmaking
    engine = create_engine(url)
    # Create only the dependency closure used by matchmaking; unrelated
    # production models have SQL-migration-only defaults and are out of scope.
    tables = {Base.metadata.tables[name] for name in ('dives', 'divers', 'sessions', 'app_users',
        'user_diver_access', 'photos_assets', 'media_cache_entries', 'media_jobs')}
    while True:
        dependencies = {fk.column.table for table in tables for fk in table.foreign_keys}
        if dependencies <= tables:
            break
        tables |= dependencies
    Base.metadata.create_all(engine, tables=tables)
    sql = (Path(__file__).parents[1] / 'migrations/add_automatic_reviews.sql').read_text()
    for _ in range(2):
        conn = engine.raw_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql)
            conn.commit()
        finally:
            conn.close()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        training = TrainingSession(date=datetime.utcnow().date()); db.add(training); db.flush()
        reviewer = AppUser(email='reviewer@example.test', display_name='Reviewer'); db.add(reviewer); db.flush()
        reviewer_id = reviewer.id
        for n in range(2):
            user = AppUser(email=f'owner{n}@example.test', display_name=f'Owner {n}')
            diver = Diver(display_name=f'Owner {n}', canonical_name=f'owner{n}')
            db.add_all([user, diver]); db.flush()
            db.add(UserDiverAccess(user_id=user.id, diver_id=diver.id))
            for index in range(4):
                video = f'owner{n}-video{index}'
                dive = Dive(session_id=training.id, diver_id=diver.id, dive_code='101B', performance='G',
                    performance_numeric=3, height='3m', dive_datetime=datetime.utcnow(), visibility='public', video_uuid=video)
                asset = PhotosAsset(video_uuid=video); db.add_all([dive, asset]); db.flush()
                db.add(MediaCacheEntry(photos_asset_id=asset.id, media_key=video, rendition='proxy_360p', storage_path='/test', size_bytes=1))
        db.commit()
    def allocate(key):
        with Session() as db:
            db.info['member_access'] = {'diver_ids': (), 'is_admin': False}
            user = db.get(AppUser, reviewer_id)
            row = matchmaking.stack(db, user, key)
            return row.id, matchmaking.queue(db, user, row.id)['items']
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(allocate, ['daily:test', 'daily:test']))
    assert results[0][0] == results[1][0] and len(results[0][1]) == 3
    assert len({i['dive']['owner_display_name'] for i in results[0][1][:2]}) == 2
    with ThreadPoolExecutor(max_workers=2) as executor:
        extra = list(executor.map(allocate, ['extra:one', 'extra:two']))
    all_ids = [i['dive_id'] for _, items in results[:1] + extra for i in items]
    assert len(all_ids) == len(set(all_ids)), 'Concurrent stacks overlapped'
    with Session() as db:
        assert db.query(ReviewStackItem).count() == 8
        user = db.get(AppUser, reviewer_id)
        dive_id = results[0][1][0]['dive_id']; video = results[0][1][0]['dive']['video_uuid']
        voted = matchmaking.rate(db, user, dive_id, 13, None, video)
        assert voted['results']['mean_score'] == 6.5
    engine.dispose()
    print('PostgreSQL migration (twice), fairness, concurrent allocation and vote: PASS')


if __name__ == '__main__':
    main()
