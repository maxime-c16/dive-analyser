"""Real PostgreSQL concurrent original events; private disposable schema only."""
import os
import threading
from uuid import uuid4
from datetime import datetime,timedelta
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine,event,select,text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

pytestmark=pytest.mark.skipif(not os.getenv('CALENDAR_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')


def test_concurrent_original_events_queue_exactly_one(monkeypatch):
    from app.database import Base
    from app.models.media import MediaJob
    from app.models.dive import Dive
    from app.models.session import Session as TrainingSession
    from app.config import get_settings
    from app.services import automatic_packages as ap
    from backend.tests.test_web_package_fenced_slots_d3b2 import _asset,_fresh_capable_agent,_seed_camera_source
    from app.services.derivative_publisher import resolve_canonical_source_revision
    url=make_url(os.environ['CALENDAR_TEST_DATABASE_URL'])
    assert url.get_backend_name()=='postgresql' and (url.database or '').startswith('calendar_test_')
    url=url.set(drivername='postgresql+psycopg2');admin=create_engine(url)
    schema='auto_packages_'+uuid4().hex
    with admin.begin() as c:c.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine=create_engine(url)
    @event.listens_for(engine,'connect')
    def set_schema(conn,_):
        with conn.cursor() as c:c.execute(f'SET search_path TO "{schema}"')
        conn.commit()
    try:
        tables={Base.metadata.tables[n] for n in ('dives','media_jobs','photos_assets','media_agents','media_blobs','media_blob_locations','media_revisions')}
        while True:
            expanded=tables|{fk.column.table for t in tables for fk in t.foreign_keys}
            if expanded==tables:break
            tables=expanded
        Base.metadata.create_all(engine,tables=list(tables))
        settings=get_settings()
        monkeypatch.setattr(settings,'media_web_packages_enabled',True)
        monkeypatch.setattr(settings,'media_web_packages_auto_ingest_enabled',True)
        monkeypatch.setattr(settings,'media_web_packages_auto_ingest_since',(datetime.utcnow()-timedelta(minutes=5)).isoformat()+'Z')
        monkeypatch.setattr(ap.shutil,'disk_usage',lambda _:SimpleNamespace(free=30*1024**3))
        factory=sessionmaker(bind=engine)
        with factory() as d:
            _fresh_capable_agent(d);a=_asset(d,uuid=str(uuid4()));training=TrainingSession(date=datetime.utcnow().date());d.add(training);d.flush()
            d.add(Dive(session_id=training.id,dive_datetime=datetime.utcnow(),dive_code='101A',performance='G',performance_numeric=3,height='3',photos_asset_id=a.id,video_uuid=a.video_uuid))
            d.add(MediaJob(photos_asset_id=a.id,media_key='legacy',rendition='proxy_720p',status='ready',request_reason='new_captioned_ingestion'))
            _seed_camera_source(d,a.video_uuid,width=1920,height=1080)
            rev,_,_=resolve_canonical_source_revision(d,a.video_uuid);uuid=a.video_uuid;revision=rev.id
        gate=threading.Barrier(2);errors=[]
        def run():
            try:
                with factory() as d:
                    gate.wait(timeout=5)
                    ap.queue_after_verified_original(d,uuid,revision,'prod');d.commit()
            except BaseException as e:errors.append(e)
        threads=[threading.Thread(target=run) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(timeout=15)
        assert not any(t.is_alive() for t in threads) and not errors,errors
        with factory() as d:
            jobs=d.execute(select(MediaJob).where(MediaJob.rendition=='web_package')).scalars().all()
            assert len(jobs)==1 and jobs[0].priority==60 and jobs[0].max_attempts==2
    finally:
        engine.dispose()
        with admin.begin() as c:c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
