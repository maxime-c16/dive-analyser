import asyncio
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.media_jobs import MediaJobProcessor


def processor(tmp_path):
    p=object.__new__(MediaJobProcessor)
    p.config=SimpleNamespace(media=SimpleNamespace(temp_dir=str(tmp_path),enabled=True,enforce_storage_thresholds=False,capabilities=['poster','web_package'],max_jobs=2,interval_seconds=60))
    p.source_vault=None;p.agent_id='test';p.sync_client=SimpleNamespace(lease_media_jobs=AsyncMock(return_value={'jobs':[]}))
    return p


@pytest.mark.parametrize('free,pressure,expected',[(8*1024**3,'0',True),(8*1024**3-1,'0',False),(9*1024**3,'1',False),(9*1024**3,'unknown',False)])
def test_disk_and_memory_measurement(tmp_path,monkeypatch,free,pressure,expected):
    import src.media_jobs as m
    paths=[]
    monkeypatch.setattr(m.shutil,'disk_usage',lambda path:(paths.append(str(path)) or SimpleNamespace(free=free)))
    monkeypatch.setattr(m.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=pressure))
    assert processor(tmp_path)._package_resources_available()==expected
    assert paths==[str(tmp_path)]


def test_unknown_memory_fails_closed(tmp_path,monkeypatch):
    import src.media_jobs as m
    monkeypatch.setattr(m.shutil,'disk_usage',lambda _:SimpleNamespace(free=9*1024**3))
    monkeypatch.setattr(m.subprocess,'run',lambda *a,**k:(_ for _ in ()).throw(subprocess.TimeoutExpired('sysctl',2)))
    assert not processor(tmp_path)._package_resources_available()


def test_pressure_strips_only_packages_before_lease(tmp_path,monkeypatch):
    p=processor(tmp_path)
    monkeypatch.setattr(p,'_package_resources_available',lambda:False)
    assert asyncio.run(p.process_once())==0
    assert p.sync_client.lease_media_jobs.call_args.kwargs['capabilities']==['poster']
    assert p.config.media.capabilities==['poster','web_package']


def test_facts_report_measurements_and_fail_closed(tmp_path,monkeypatch):
    import src.media_jobs as m
    monkeypatch.setattr(m.shutil,'disk_usage',lambda _:SimpleNamespace(free=9*1024**3))
    monkeypatch.setattr(m.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout='0\n'))
    facts=m.package_resource_facts(str(tmp_path))
    assert facts['available'] and facts['scratch_free_bytes']==9*1024**3 and facts['memory_pressure']=='0'
    monkeypatch.setattr(m.shutil,'disk_usage',lambda _:(_ for _ in ()).throw(OSError()))
    facts=m.package_resource_facts(str(tmp_path))
    assert not facts['available'] and facts['scratch_free_bytes'] is None and facts['memory_pressure']=='0'


def test_heartbeat_reports_package_facts_without_dropping_vault_status(tmp_path,monkeypatch):
    import src.main as main
    sent=[]
    stop=asyncio.Event()

    async def heartbeat(payload):
        sent.append(payload);stop.set()

    config=SimpleNamespace(
        photos=SimpleNamespace(library_path=str(tmp_path),health_probe_timeout_seconds=1),
        media=SimpleNamespace(capabilities=['poster','web_package'],temp_dir=str(tmp_path),
                              source_vault=SimpleNamespace(enabled=False)),
        agent=SimpleNamespace(id='mac-media-01',hostname='mac'))
    monkeypatch.setattr(main,'_probe_photos_database',lambda _:1)
    monkeypatch.setattr(main,'package_resource_facts',lambda d:{'available':True,'scratch_free_bytes':1,'memory_pressure':'0','measured_at':'t'})
    asyncio.run(main.run_agent_heartbeat_loop(config,SimpleNamespace(heartbeat_media_agent=heartbeat),stop))
    assert sent[0]['storage_status']=={'package_resources':{'available':True,'scratch_free_bytes':1,'memory_pressure':'0','measured_at':'t'}}
    config.media.capabilities=['poster']
    sent.clear();stop.clear()
    asyncio.run(main.run_agent_heartbeat_loop(config,SimpleNamespace(heartbeat_media_agent=heartbeat),stop))
    assert sent[0]['storage_status'] is None
