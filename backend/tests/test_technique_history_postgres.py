"""Isolated production-dialect history checks; never connect to application DB."""
import os
from pathlib import Path
import pytest
from sqlalchemy import create_engine, text
from app.services.technique_history_sql import RESOLVED, comparison_sql

@pytest.fixture()
def pg():
    url=os.environ.get('TECHNIQUE_TEST_DATABASE_URL')
    if not url: pytest.skip('Disposable PostgreSQL required')
    from sqlalchemy.engine import make_url
    assert make_url(url).database.startswith('calendar_test_')
    engine=create_engine(url)
    with engine.begin() as c:
        c.execute(text('DROP SCHEMA public CASCADE'));c.execute(text('CREATE SCHEMA public'))
        c.execute(text('''CREATE TABLE divers(id serial primary key); CREATE TABLE sessions(id serial primary key);
        CREATE TABLE app_users(id serial primary key);
        CREATE TABLE dives(id serial primary key,session_id int,diver_id int,dive_code text,
        platform_type text,height text,position text,is_sync boolean,performance text,dive_datetime timestamp);
        CREATE TABLE dive_modifiers(dive_id int,modifier_code text);
        INSERT INTO divers VALUES(1); INSERT INTO sessions VALUES(1);
        INSERT INTO dives VALUES(1,1,1,'103','springboard','3','B',false,'G','2026-01-01'); SELECT setval('dives_id_seq',1);'''))
        migration=(Path(__file__).parents[1]/'migrations/add_technique_history.sql').read_text().replace('BEGIN;','').replace('COMMIT;','')
        c.execute(text(migration));c.execute(text(migration))
    yield engine
    engine.dispose()

def test_immutable_ingest_and_display_edits(pg):
    with pg.begin() as c:
        c.execute(text("UPDATE dives SET dive_datetime='2026-02-01' WHERE id=1"))
        assert str(c.scalar(text('SELECT history_occurred_at FROM dives WHERE id=1')))=='2026-01-01 00:00:00'
        c.execute(text("INSERT INTO dives(session_id,diver_id,dive_code,dive_datetime) VALUES(1,1,'103','2025-01-01')"))
        assert str(c.scalar(text('SELECT history_occurred_at FROM dives WHERE id=2')))=='2025-01-01 00:00:00'
    with pytest.raises(Exception,match='Immutable history occurrence'):
        with pg.begin() as c:c.execute(text("UPDATE dives SET history_occurred_at='2024-01-01'"))

def test_sql_full_scope_precedence_and_conflicting_recorded(pg):
    with pg.begin() as c:
        c.execute(text("""INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0);
        INSERT INTO techniques(id,track_id,label,created_at) VALUES(1,1,'A',now()),(2,1,'B',now());
        INSERT INTO technique_episodes(id,track_id,technique_id,scope,apparatus,height,start_at,start_id,precision,timezone,gap,notes,deleted)
        VALUES(1,1,1,'1','springboard','3','2025-01-01',0,'date','UTC',false,'',false),
        (2,1,2,'103','springboard','3','2026-01-01',1,'attempt','UTC',false,'',false);
        INSERT INTO dives(session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,dive_datetime)
        SELECT 1,1,'103','springboard','3','B',false,'P','2026-01-02' FROM generate_series(1,120);
        INSERT INTO technique_assignments(track_id,dive_id,diver_id,code,apparatus,height,position,sync,state,technique_id)
        VALUES(1,1,1,'103','springboard','3','B',false,'technique',1);"""))
        p=dict(diver=1,track=1,code='103',apparatus='springboard',height='3',position='B',sync=False,left=1,right=2,left_identity=1,right_identity=2,modifiers='')
        resolved=c.execute(text(RESOLVED+' SELECT * FROM resolved ORDER BY id LIMIT 1'),p).mappings().one()
        assert resolved['episode_id']==2 and resolved['use_id']==1 and resolved['source']=='recorded'
        result=c.execute(text(comparison_sql()),p).mappings().one()
        assert result['eligible']==121 and result['scored']==121 and result['median']==10
        assert result['recorded_conflicting']==1 and result['inferred_only']==120
        c.execute(text("UPDATE dives SET diver_id=NULL WHERE id=1"))
        assert c.scalar(text(RESOLVED+' SELECT count(*) FROM resolved'),p)==120

def test_mutations_preserve_upcoming_boundary_and_reject_stale_revision(pg,monkeypatch):
    from types import SimpleNamespace
    from datetime import datetime
    from sqlalchemy.orm import Session
    from fastapi import HTTPException
    from app.api.v1 import technique_history as api
    monkeypatch.setattr(api,'owner',lambda *args,**kwargs:SimpleNamespace(id=1))
    with pg.begin() as c:
        c.execute(text("INSERT INTO app_users VALUES(1); INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0)"))
    def body(rev,day,label):
        return api.Change(code='103',scope='103',apparatus='springboard',height='3',position='B',revision=rev,start_at=datetime(2026,1,day),label=label)
    with Session(pg) as db:
        first=api.change(1,1,body(0,1,'A'),None,db)
        second=api.change(1,1,body(1,20,'B'),None,db)
        middle=api.change(1,1,body(2,10,'C'),None,db)
        assert middle['episode']['end_at']=='2026-01-20T00:00:00'
        assert db.scalar(text('SELECT end_at FROM technique_episodes WHERE id=:id'),{'id':first['episode']['id']})==datetime(2026,1,10)
        with pytest.raises(HTTPException) as exc: api.change(1,1,body(2,15,'stale'),None,db)
        assert exc.value.status_code==409
        db.rollback()
        api.undo(1,1,api.RevisionInput(revision=3),None,db)
        assert db.scalar(text('SELECT end_at FROM technique_episodes WHERE id=:id'),{'id':first['episode']['id']})==datetime(2026,1,20)


def test_shared_track_lock_serializes_family_and_code_writers(pg):
    from sqlalchemy.orm import Session
    from app.api.v1.technique_history import track_for
    with pg.begin() as c:c.execute(text("INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0)"))
    with Session(pg) as left,Session(pg) as right:
        track_for(left,1,1,0)
        right.execute(text("SET LOCAL lock_timeout='50ms'"))
        with pytest.raises(Exception,match='lock timeout'):track_for(right,1,1,0)
        right.rollback();left.rollback()
        assert track_for(right,1,1,0).revision==0

def test_mixed_session_is_track_scoped_and_explicit_attempt_wins(pg):
    with pg.begin() as c:
        c.execute(text("""INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'Hurdle',0),(2,1,'Entry',0);
        INSERT INTO technique_session_states(track_id,session_id,code,apparatus,height,position,sync,state)
        VALUES(1,1,'103','springboard','3','B',false,'mixed');
        INSERT INTO techniques(id,track_id,label,created_at) VALUES(1,1,'A',now());"""))
        p=dict(diver=1,track=1,code='103',apparatus='springboard',height='3',position='B',sync=False)
        assert c.scalar(text(RESOLVED+' SELECT state FROM resolved'),p)=='mixed'
        assert c.scalar(text(RESOLVED+' SELECT state FROM resolved'),dict(p,track=2))=='unrecorded'
        c.execute(text("""INSERT INTO technique_assignments(track_id,dive_id,diver_id,code,apparatus,height,position,sync,state,technique_id)
        VALUES(1,1,1,'103','springboard','3','B',false,'technique',1)"""))
        assert c.scalar(text(RESOLVED+' SELECT state FROM resolved'),p)=='technique'
        c.execute(text("UPDATE dives SET height='1' WHERE id=1"))
        assert c.scalar(text(RESOLVED+' SELECT state FROM resolved'),dict(p,height='1'))=='unrecorded'

def test_recorded_partition_uses_union_and_keeps_conflict_on_its_identity(pg):
    with pg.begin() as c:
        c.execute(text("""INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0);
        INSERT INTO techniques(id,track_id,label,created_at) VALUES(1,1,'A',now()),(2,1,'B',now());
        INSERT INTO technique_episodes(id,track_id,technique_id,scope,apparatus,height,start_at,start_id,end_at,end_id,precision,timezone,gap,notes,deleted)
        VALUES(1,1,1,'103','springboard','3','2025-01-01',0,'2026-01-01',1,'date','UTC',false,'',false),
        (2,1,2,'103','springboard','3','2026-01-01',1,NULL,NULL,'attempt','UTC',false,'',false);
        INSERT INTO technique_assignments(track_id,dive_id,diver_id,code,apparatus,height,position,sync,state,technique_id)
        VALUES(1,1,1,'103','springboard','3','B',false,'technique',1);"""))
        p=dict(diver=1,track=1,code='103',apparatus='springboard',height='3',position='B',sync=False,left=1,right=2,left_identity=1,right_identity=2,modifiers='')
        result=c.execute(text(comparison_sql(recorded=True)),p).mappings().one()
        assert result['side']==0 and result['recorded_conflicting']==1 and result['eligible']==1
        assert result['median']==7 and result['q1'] is None
