"""New-original event, resource stops, background priority and replay safety."""
from datetime import datetime, timedelta
from types import SimpleNamespace
import pytest
from app.config import get_settings
from app.models.media import MediaJob
from app.models.dive import Dive
from app.services import automatic_packages as ap
from backend.tests.test_web_package_fenced_slots_d3b2 import _asset, _seed_camera_source, _fresh_capable_agent


@pytest.fixture
def automatic(test_db, monkeypatch):
    settings=get_settings()
    monkeypatch.setattr(settings,'media_web_packages_enabled',True)
    monkeypatch.setattr(settings,'media_web_packages_auto_ingest_enabled',True)
    monkeypatch.setattr(settings,'media_web_packages_auto_ingest_since',(datetime.utcnow()-timedelta(minutes=5)).isoformat()+'Z')
    monkeypatch.setattr(ap.shutil,'disk_usage',lambda _:SimpleNamespace(free=30*1024**3))
    _fresh_capable_agent(test_db)
    asset=_asset(test_db)
    test_db.add(Dive(dive_datetime=datetime.utcnow(),session_id=1,dive_code='101A',performance='G',performance_numeric=3,height='3',photos_asset_id=asset.id,video_uuid=asset.video_uuid))
    _,trigger,_=__import__('app.services.media_jobs',fromlist=['create_or_reuse_media_job']).create_or_reuse_media_job(test_db,asset,'proxy_720p','new_captioned_ingestion')
    trigger.status='ready'
    _seed_camera_source(test_db,asset.video_uuid,width=1920,height=1080)
    from app.services.derivative_publisher import resolve_canonical_source_revision
    rev,_,_=resolve_canonical_source_revision(test_db,asset.video_uuid)
    test_db.flush()
    return asset,trigger,rev


def test_original_event_queues_once_priority60(test_db,automatic):
    asset,_,rev=automatic
    job=ap.queue_after_verified_original(test_db,asset.video_uuid,rev.id,'PROD')
    assert job.priority==60 and job.max_attempts==2
    assert ap.queue_after_verified_original(test_db,asset.video_uuid,rev.id,'PROD') is None
    job.status='failed';test_db.flush()
    assert ap.queue_after_verified_original(test_db,asset.video_uuid,rev.id,'PROD') is None
    assert test_db.query(MediaJob).filter_by(rendition='web_package').count()==1


@pytest.mark.parametrize('case',['old','unrelated','dev','wrong_revision','flag_off','no_cutoff','naive_cutoff','disk_low','disk_unknown','no_worker'])
def test_original_event_refuses_unqualified(test_db,automatic,monkeypatch,case):
    a,t,r=automatic;env='PROD';rev=r.id;s=get_settings()
    if case=='old':t.created_at=datetime.utcnow()-timedelta(days=1)
    if case=='unrelated':t.request_reason='interactive'
    if case=='dev':env='DEV'
    if case=='wrong_revision':rev+=1000
    if case=='flag_off':monkeypatch.setattr(s,'media_web_packages_auto_ingest_enabled',False)
    if case=='no_cutoff':monkeypatch.setattr(s,'media_web_packages_auto_ingest_since','')
    if case=='naive_cutoff':monkeypatch.setattr(s,'media_web_packages_auto_ingest_since','2026-01-01')
    if case=='disk_low':monkeypatch.setattr(ap.shutil,'disk_usage',lambda _:SimpleNamespace(free=24*1024**3))
    if case=='disk_unknown':monkeypatch.setattr(ap.shutil,'disk_usage',lambda _:(_ for _ in ()).throw(OSError()))
    if case=='no_worker':
        from app.models.media import MediaAgent
        test_db.query(MediaAgent).update({'leasing_enabled':False})
    test_db.flush()
    assert ap.queue_after_verified_original(test_db,a.video_uuid,rev,env) is None
    assert test_db.query(MediaJob).filter_by(rendition='web_package').count()==0


@pytest.mark.parametrize('states,allowed',[(['failed','unavailable'],False),(['failed','failed'],False),(['ready','failed'],True),(['failed'],True)])
def test_two_terminal_failures_pause(test_db,automatic,states,allowed):
    a,_,_=automatic
    for i,state in enumerate(states):test_db.add(MediaJob(photos_asset_id=a.id,media_key=f'failed-{i}',rendition='web_package',status=state))
    test_db.flush()
    assert ap.package_resources_available(test_db)==allowed


def test_low_server_disk_prevents_package_lease_but_keeps_legacy(test_db,automatic,monkeypatch):
    from app.services.media_jobs import lease_media_jobs,create_or_reuse_media_job
    from app.schemas.media import MediaJobLeaseRequest
    a,_,_=automatic
    _,p,_=create_or_reuse_media_job(test_db,a,'web_package','new_captioned_ingestion')
    monkeypatch.setattr(ap.shutil,'disk_usage',lambda _:SimpleNamespace(free=24*1024**3))
    leases=lease_media_jobs(test_db,MediaJobLeaseRequest(agent_id='mac-media-01',capabilities=['web_package'],max_jobs=1,supports_lease_token=True))
    assert leases==[] and p.status=='queued' and p.attempts==0


def test_real_commit_route_queues_after_source_is_verified(test_db, automatic):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db
    from backend.tests.test_media_backbone_commit_api import _document, TEST_API_KEY
    a,_,_=automatic
    doc=_document(video_uuid=a.video_uuid)
    saved=dict(app.dependency_overrides)
    app.dependency_overrides[get_db]=lambda:test_db
    try:
        client=TestClient(app,headers={'X-API-Key':TEST_API_KEY})
        response=client.post('/api/v1/media/backbone/commit',json=doc)
        assert response.status_code==200,response.text
        assert test_db.query(MediaJob).filter_by(rendition='web_package').count()==1
        response=client.post('/api/v1/media/backbone/commit',json=doc)
        assert response.status_code==200,response.text
        assert test_db.query(MediaJob).filter_by(rendition='web_package').count()==1
    finally:
        app.dependency_overrides.clear();app.dependency_overrides.update(saved)
