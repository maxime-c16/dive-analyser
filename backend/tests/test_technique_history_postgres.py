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
        c.execute(text('''CREATE TABLE divers(id serial primary key,display_name text DEFAULT 'Test diver'); CREATE TABLE sessions(id serial primary key,location text);
        CREATE TABLE app_users(id serial primary key);
        CREATE TABLE dives(id serial primary key,session_id int,diver_id int,dive_code text,
        platform_type text,height text,position text,is_sync boolean,performance text,dive_datetime timestamp,video_uuid text,phase1_performance text,phase2_performance text,created_at timestamp DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE dive_modifiers(dive_id int,modifier_code text);
        INSERT INTO divers VALUES(1); INSERT INTO sessions VALUES(1);
        INSERT INTO dives VALUES(1,1,1,'103','springboard','3','B',false,'G','2026-01-01',NULL,NULL,NULL,now()); SELECT setval('dives_id_seq',1);'''))
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
        sessions=c.execute(text(comparison_sql(session_weight=True)),p).mappings().one()
        assert sessions['observations']==1 and sessions['q1'] is None and sessions['median']==10
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

def test_comparison_one_sql_statement_and_page_independent_statistics(pg):
    from sqlalchemy import event
    calls=[]
    event.listen(pg,'before_cursor_execute',lambda *args:calls.append(args[2]))
    with pg.begin() as c:
        params=dict(diver=1,track=1,code='103',apparatus='springboard',height='3',position='B',sync=False,left=1,right=2,left_identity=1,right_identity=2,modifiers='')
        before=len(calls)
        assert c.execute(text(comparison_sql(session_weight=True)),params).mappings().all()==[]
        assert len(calls)-before==1

def test_owner_required_even_when_dives_are_public(pg,monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.orm import Session
    from fastapi import HTTPException
    from app.api.v1 import technique_history as api
    from app.models.user_auth import UserDiverAccess
    UserDiverAccess.__table__.create(pg)
    monkeypatch.setattr(api,'optional_session_user',lambda *args:SimpleNamespace(id=1,is_active=True,is_admin=True))
    with Session(pg) as db:
        with pytest.raises(HTTPException) as exc:api.owner(None,db,1)
        assert exc.value.status_code==403
        db.execute(text('INSERT INTO app_users VALUES(1)'))
        db.add(UserDiverAccess(user_id=1,diver_id=1,access_kind='OWNER'));db.commit()
        assert api.owner(None,db,1).id==1
        db.query(UserDiverAccess).delete();db.commit()
        with pytest.raises(HTTPException):api.owner(None,db,1)

def test_api_sql_pages_and_date_normalization(pg,monkeypatch):
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_history as api
    from types import SimpleNamespace
    from datetime import datetime
    monkeypatch.setattr(api,'owner',lambda *a,**k:SimpleNamespace(id=1))
    with pg.begin() as c:c.execute(text("INSERT INTO app_users VALUES(1); INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0)"))
    with Session(pg) as db:
        b=api.Change(code='103',scope='103',apparatus='springboard',height='3',position='B',label='A',revision=0,start_at=datetime(2026,1,1,1),timezone='Europe/Paris')
        preview=api.preview(1,1,b,None,db)
        assert preview['change']['start_at']==datetime(2026,1,1)
        assert preview['change']['normalized'] is True
        created=api.change(1,1,api.Change(**preview['change']),None,db)
        assert created['episode']['start_at']=='2026-01-01T00:00:00'
        page=api.attempts(1,1,api.ReadInput(code='103',apparatus='springboard',height='3',position='B'),None,db)
        assert page['items'][0]['use_label']=='A' and page['next'] is None
        assert page['items'][0]['source']=='inferred'

def test_sql_rating_preserves_app_phase_weighting_and_missing_values(pg):
    from app.services.performance_scoring import attempt_score_10
    with pg.begin() as c:
        c.execute(text("UPDATE dives SET phase1_performance='G',phase2_performance='P' WHERE id=1"))
        p=dict(diver=1,track=1,code='103',apparatus='springboard',height='3',position='B',sync=False)
        assert float(c.scalar(text(RESOLVED+' SELECT rating FROM resolved'),p))==pytest.approx(attempt_score_10('G','G','P'))
        c.execute(text('UPDATE dives SET performance=NULL WHERE id=1'))
        assert float(c.scalar(text(RESOLVED+' SELECT rating FROM resolved'),p))==pytest.approx(attempt_score_10(None,'G','P'))
        c.execute(text('UPDATE dives SET phase1_performance=NULL,phase2_performance=NULL WHERE id=1'))
        assert c.scalar(text(RESOLVED+' SELECT rating FROM resolved'),p) is None

def test_copy_is_independent_and_preserves_target_upcoming_boundary(pg,monkeypatch):
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_history as api
    from types import SimpleNamespace
    from datetime import datetime
    monkeypatch.setattr(api,'owner',lambda *a,**k:SimpleNamespace(id=1))
    with pg.begin() as c:c.execute(text("INSERT INTO app_users VALUES(1); INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0)"))
    with Session(pg) as db:
        common=dict(code='103',apparatus='springboard',height='3',position='B',timezone='UTC')
        source=api.change(1,1,api.Change(**common,scope='103',label='A',revision=0,start_at=datetime(2026,1,1)),None,db)
        api.change(1,1,api.Change(**common,scope='1',label='B',revision=1,start_at=datetime(2026,2,1)),None,db)
        copied=api.copy_once(1,1,api.CopyInput(revision=2,episode_id=source['episode']['id'],targets=[api.CopyTarget(scope='1',apparatus='springboard',height='3')],commit=True),None,db)
        result=db.execute(text('SELECT source_episode_id,end_at FROM technique_episodes WHERE id=:id'),{'id':copied['ids'][0]}).one()
        assert result[0]==source['episode']['id'] and result[1]==datetime(2026,2,1)
        edit=api.Change(**common,scope='103',label='C',revision=3,start_at=datetime(2026,1,1),episode_id=source['episode']['id'])
        api.change(1,1,edit,None,db)
        assert db.scalar(text('SELECT technique_id FROM technique_episodes WHERE id=:id'),{'id':copied['ids'][0]})==source['episode']['technique_id']

def test_edit_moves_previous_end_and_undo_restores_both(pg,monkeypatch):
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_history as api
    from types import SimpleNamespace
    from datetime import datetime
    monkeypatch.setattr(api,'owner',lambda *a,**k:SimpleNamespace(id=1))
    with pg.begin() as c:c.execute(text("INSERT INTO app_users VALUES(1); INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0)"))
    with Session(pg) as db:
        common=dict(code='103',scope='103',apparatus='springboard',height='3',position='B')
        a=api.change(1,1,api.Change(**common,label='A',revision=0,start_at=datetime(2026,1,1)),None,db)
        b=api.change(1,1,api.Change(**common,label='B',revision=1,start_at=datetime(2026,1,10)),None,db)
        api.change(1,1,api.Change(**common,label='B',revision=2,start_at=datetime(2026,1,15),episode_id=b['episode']['id']),None,db)
        assert db.scalar(text('SELECT end_at FROM technique_episodes WHERE id=:id'),{'id':a['episode']['id']})==datetime(2026,1,15)
        api.undo(1,1,api.RevisionInput(revision=3),None,db)
        assert db.scalar(text('SELECT end_at FROM technique_episodes WHERE id=:id'),{'id':a['episode']['id']})==datetime(2026,1,10)
        assert db.scalar(text('SELECT start_at FROM technique_episodes WHERE id=:id'),{'id':b['episode']['id']})==datetime(2026,1,10)

def test_correction_requires_all_track_revisions_and_preserves_anchor_key(pg,monkeypatch):
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_history as api
    from types import SimpleNamespace
    from datetime import datetime
    from fastapi import HTTPException
    monkeypatch.setattr(api,'owner',lambda *a,**k:SimpleNamespace(id=1))
    with pg.begin() as c:c.execute(text("INSERT INTO app_users VALUES(1); INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0),(2,1,'Entry',0)"))
    with Session(pg) as db:
        a=api.change(1,1,api.Change(code='103',scope='103',apparatus='springboard',height='3',position='B',label='A',revision=0,start_at=datetime(2026,1,1),anchor_id=1),None,db)
        b=api.CorrectionInput(revision=1,attempt_id=1,occurred_at=datetime(2026,1,2))
        preview=api.correct_order(1,1,b,None,db)
        with pytest.raises(HTTPException) as exc:api.correct_order(1,1,api.CorrectionInput(**dict(b.model_dump(),commit=True)),None,db)
        assert exc.value.status_code==409
        db.rollback()
        api.correct_order(1,1,api.CorrectionInput(**dict(b.model_dump(),commit=True,track_revisions=preview['preview']['track_revisions'])),None,db)
        assert db.scalar(text('SELECT history_occurred_at FROM dives WHERE id=1'))==datetime(2026,1,2)
        assert db.scalar(text('SELECT start_at FROM technique_episodes WHERE id=:id'),{'id':a['episode']['id']})==datetime(2026,1,1)
        assert db.scalar(text('SELECT revision FROM technique_tracks WHERE id=2'))==1

def test_episode_pages_bound_materialization_and_response_bytes(pg,monkeypatch):
    import json,tracemalloc
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_history as api
    from types import SimpleNamespace
    monkeypatch.setattr(api,'owner',lambda *a,**k:SimpleNamespace(id=1))
    with pg.begin() as c:
        c.execute(text("""INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0);
        INSERT INTO technique_episodes(track_id,scope,apparatus,height,start_at,start_id,precision,timezone,gap,notes,deleted)
        SELECT 1,'103','springboard','3','2026-01-01'::timestamp+n*interval '1 minute',0,'date','UTC',true,repeat('x',2000),false FROM generate_series(1,75) n"""))
    calls=[]
    event.listen(pg,'before_cursor_execute',lambda *args:calls.append(args[2]))
    with Session(pg) as db:
        tracemalloc.start()
        first=api.episodes(1,1,None,0,db)
        second=api.episodes(1,1,None,first['next'],db)
        _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        size=len(json.dumps(first,default=str).encode())
        assert len(first['items'])==50 and len(second['items'])==25 and second['next'] is None
        assert len(calls)<=6 and size<256*1024 and peak<2*1024*1024
        print(f'episode detail proof: {len(calls)} SQL calls for two pages, {size} response bytes, {peak} peak traced bytes')

def test_chart_curve_uses_preceding_sessions_across_page_boundary(pg,monkeypatch):
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_history as api
    from types import SimpleNamespace
    monkeypatch.setattr(api,'owner',lambda *a,**k:SimpleNamespace(id=1))
    with pg.begin() as c:
        c.execute(text("""INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0);
        INSERT INTO techniques(id,track_id,label,created_at) VALUES(1,1,'A',now());
        INSERT INTO technique_episodes(track_id,technique_id,scope,apparatus,height,start_at,start_id,precision,timezone,gap,notes,deleted)
        VALUES(1,1,'103','springboard','3','2025-01-01',0,'date','UTC',false,'',false);
        INSERT INTO dives(session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,dive_datetime)
        SELECT n,1,'103','springboard','3','B',false,CASE WHEN n<=50 THEN 'P' ELSE 'F' END,'2026-01-01'::timestamp+n*interval '1 day' FROM generate_series(2,61) n"""))
    with Session(pg) as db:
        common=dict(code='103',apparatus='springboard',height='3',position='B',episode=1)
        first=api.chart(1,1,api.ChartInput(**common),None,db)
        assert len(first['items'])==50
        second=api.chart(1,1,api.ChartInput(**common,after=first['next']),None,db)
        assert second['items'][0]['median']==0
        assert second['items'][0]['curve_median']==10

def test_bulk_recorded_identity_and_deleted_episode_provenance_survive(pg,monkeypatch):
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_history as api
    from types import SimpleNamespace
    from datetime import datetime
    monkeypatch.setattr(api,'owner',lambda *a,**k:SimpleNamespace(id=1))
    with pg.begin() as c:c.execute(text("INSERT INTO app_users VALUES(1); INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0)"))
    with Session(pg) as db:
        context=dict(code='103',apparatus='springboard',height='3',position='B')
        e=api.change(1,1,api.Change(**context,scope='103',label='A',revision=0,start_at=datetime(2025,1,1)),None,db)
        api.assign(1,1,api.Bulk(**context,revision=1,ids=[1],state='technique',technique_id=e['episode']['technique_id']),None,db)
        api.delete_episode(1,1,e['episode']['id'],api.DeleteInput(revision=2,commit=True),None,db)
        attempt=api.attempts(1,1,api.ReadInput(**context),None,db)['items'][0]
        assert attempt['use_label']=='A' and attempt['source']=='recorded'
        assert attempt['recorded_episode_deleted'] and attempt['recorded_episode_id']==e['episode']['id']

def test_track_chart_splits_same_session_and_resets_a_b_a_segments(pg,monkeypatch):
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_history as api
    from types import SimpleNamespace
    monkeypatch.setattr(api,'owner',lambda *a,**k:SimpleNamespace(id=1))
    with pg.begin() as c:
        c.execute(text("""INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0);
        INSERT INTO techniques(id,track_id,label,created_at) VALUES(1,1,'A',now()),(2,1,'B',now());
        INSERT INTO dives(session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,dive_datetime)
        VALUES(1,1,'103','springboard','3','B',false,'P','2026-01-02'),(1,1,'103','springboard','3','B',false,'F','2026-01-03');
        INSERT INTO technique_episodes(id,track_id,technique_id,scope,apparatus,height,start_at,start_id,end_at,end_id,precision,timezone,gap,notes,deleted)
        VALUES(1,1,1,'103','springboard','3','2025-01-01',0,'2026-01-02',2,'date','UTC',false,'',false),
        (2,1,2,'103','springboard','3','2026-01-02',2,'2026-01-03',3,'attempt','UTC',false,'',false),
        (3,1,1,'103','springboard','3','2026-01-03',3,NULL,NULL,'attempt','UTC',false,'',false)"""))
    with Session(pg) as db:
        body=api.TrackChartInput(code='103',apparatus='springboard',height='3',position='B')
        result=api.track_chart(1,1,body,None,db)
        assert len(result['items'])==3 and len(result['boundaries'])==3
        assert [float(r['curve_median']) for r in result['items']]==[7,10,0]
        assert len({r['segment'] for r in result['items']})==3
        db.execute(text("INSERT INTO technique_session_states(track_id,session_id,code,apparatus,height,position,sync,state) VALUES(1,1,'103','springboard','3','B',false,'mixed')"));db.commit()
        mixed=api.track_chart(1,1,body,None,db)
        assert all(r['curve_median'] is None for r in mixed['items'])

def test_compare_api_coverage_and_modifier_inventory(pg,monkeypatch):
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_history as api
    from types import SimpleNamespace
    from datetime import datetime
    from fastapi import HTTPException
    monkeypatch.setattr(api,'owner',lambda *a,**k:SimpleNamespace(id=1))
    with pg.begin() as c:
        c.execute(text("""INSERT INTO app_users VALUES(1); INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0);
        INSERT INTO dives(session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,dive_datetime)
        VALUES(1,1,'103','springboard','3','B',false,'P','2026-01-02')"""))
    with Session(pg) as db:
        common=dict(code='103',apparatus='springboard',height='3',position='B')
        a=api.change(1,1,api.Change(**common,scope='103',label='A',revision=0,start_at=datetime(2025,1,1)),None,db)
        b=api.change(1,1,api.Change(**common,scope='103',label='B',revision=1,start_at=datetime(2026,1,2)),None,db)
        api.session_state(1,1,api.SessionFlag(**common,revision=2,session_id=1,state='mixed'),None,db)
        api.assign(1,1,api.Bulk(**common,revision=3,ids=[1],state='technique',technique_id=a['episode']['technique_id']),None,db)
        pair=dict(left=a['episode']['id'],right=b['episode']['id'])
        inventory=api.modifier_sets(1,1,api.Inventory(**common,**pair),None,db)
        assert inventory['items'][0]['left_eligible']==1 and inventory['items'][0]['right_eligible']==1
        periods=api.compare(1,1,api.Compare(**common,**pair,modifiers=''),None,db)
        assert periods['sides'][1]['mixed_unknown']==1 and periods['excluded']['not_recorded']==0
        recorded=api.compare(1,1,api.Compare(**common,**pair,modifiers='',mode='recorded'),None,db)
        assert recorded['recorded_eligible']==1 and recorded['excluded']['not_recorded']==1
        with pytest.raises(HTTPException) as exc:api.compare(1,1,api.Compare(**dict(common,height='1'),**pair,modifiers=''),None,db)
        assert exc.value.status_code==422

def test_context_inventory_is_complete_and_owner_scoped(pg,monkeypatch):
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_history as api
    from app.models.user_auth import UserDiverAccess
    from types import SimpleNamespace
    monkeypatch.setattr(api,'optional_session_user',lambda *a:SimpleNamespace(id=1,is_active=True))
    UserDiverAccess.__table__.create(pg)
    with Session(pg) as db:
        db.execute(text("""INSERT INTO app_users VALUES(1); INSERT INTO divers(id) VALUES(2);
        INSERT INTO dives(session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,dive_datetime)
        VALUES(1,1,'103','springboard','1','B',false,'P','2026-01-02'),(1,2,'103','springboard','3','B',false,'P','2026-01-03')"""))
        db.add(UserDiverAccess(user_id=1,diver_id=1,access_kind='OWNER'));db.commit()
        result=api.context_inventory(None,'103','',db)
        assert len(result['items'])==2 and {r['height'] for r in result['items']}=={'1','3'}
        assert all(r['diver_id']==1 for r in result['items'])


def test_browse_window_can_seek_an_anchor_and_page_both_directions(pg, monkeypatch):
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_history as api
    monkeypatch.setattr(api, 'owner', lambda *args, **kwargs: None)
    with pg.begin() as c:
        c.execute(text("INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0)"))
        c.execute(text("""INSERT INTO dives(session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,dive_datetime)
        SELECT 1,1,'103','springboard','3','B',false,'G',timestamp '2026-01-02'+n*interval '1 minute' FROM generate_series(1,150) n"""))
    context = dict(code='103', apparatus='springboard', height='3', position='B', sync=False)
    with Session(pg) as db:
        first = api.attempts(1,1,api.ReadInput(**context),None,db)
        assert len(first['items']) == 50 and first['previous'] is None and first['next'] == 50
        second = api.attempts(1,1,api.ReadInput(**context, after=first['next']),None,db)
        assert [r['id'] for r in second['items']] == list(range(51,101))
        backwards = api.attempts(1,1,api.ReadInput(**context,before=second['items'][0]['id']),None,db)
        assert [r['id'] for r in backwards['items']] == list(range(1,51))
        assert backwards['previous'] is None
        focused = api.attempts(1,1,api.ReadInput(**context,around=80),None,db)
        assert [r['id'] for r in focused['items']] == list(range(55,105))
        assert focused['previous'] == 55 and focused['next'] == 104
        # An anchor belonging to a different exact context cannot retrieve it.
        hidden = api.attempts(1,1,api.ReadInput(**dict(context,code='205'),around=80),None,db)
        assert hidden['items'] == []
        with pytest.raises(Exception,match='Choose one navigation cursor'):
            api.attempts(1,1,api.ReadInput(**context,around=80,before=90),None,db)


def test_browse_session_position_and_technique_inventory_are_complete(pg, monkeypatch):
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_history as api
    monkeypatch.setattr(api, 'owner', lambda *args, **kwargs: None)
    with pg.begin() as c:
        c.execute(text("INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0)"))
        c.execute(text("INSERT INTO techniques(track_id,label,created_at) SELECT 1,'Cue '||n,now() FROM generate_series(1,75) n"))
        c.execute(text("INSERT INTO dives(session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,dive_datetime) SELECT 1,1,'103','springboard','3','B',false,'G',timestamp '2026-01-02'+n*interval '1 minute' FROM generate_series(1,100) n"))
    with Session(pg) as db:
        context = dict(code='103', apparatus='springboard', height='3', position='B', sync=False)
        page = api.attempts(1,1,api.ReadInput(**context,after=50),None,db)
        assert page['items'][0]['session_index'] == 51
        assert page['items'][0]['session_total'] == 101
        assert page['items'][0]['history_total'] == 101
        assert page['items'][0]['history_index'] == 51
        names = api.technique_choices(1,1,None,0,db)
        assert len(names['items']) == 50 and names['next'] == 50
        assert len(api.technique_choices(1,1,None,names['next'],db)['items']) == 25


def test_history_local_dates_normalize_without_silently_changing_saved_keys():
    from datetime import datetime
    from app.api.v1.technique_history import local_boundary
    assert local_boundary(datetime(2026,7,1,12), 'Europe/Paris') == datetime(2026,7,1,10)
    assert local_boundary(datetime(2026,1,1,12), 'Europe/Paris') == datetime(2026,1,1,11)
    with pytest.raises(Exception, match='Nonexistent local time'):
        local_boundary(datetime(2026,3,29,2,30), 'Europe/Paris')

def test_date_seek_includes_clips_on_both_sides_without_retaining_a_date_filter(pg,monkeypatch):
    from sqlalchemy.orm import Session
    from types import SimpleNamespace
    from app.api.v1 import technique_history as api
    monkeypatch.setattr(api,'owner',lambda *args,**kwargs:SimpleNamespace(id=1))
    with pg.begin() as c:
        c.execute(text("INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0)"))
        c.execute(text("""INSERT INTO dives(session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,dive_datetime)
        SELECT 1,1,'103','springboard','3','B',false,'G','2026-01-01'::timestamp + n * interval '1 day' FROM generate_series(1,100) n"""))
    with Session(pg) as db:
        page=api.attempts(1,1,api.ReadInput(code='103',apparatus='springboard',height='3',position='B',seek_at='2026-02-10T00:00:00'),None,db)
        ids=[item['id'] for item in page['items']]
        assert ids.index(page['focus_id'])==25
        assert page['items'][24]['history_occurred_at'] < page['items'][25]['history_occurred_at']
        assert page['previous'] is not None


def test_joint_setup_preview_preserves_existing_boundaries_and_counts_final_intervals(pg,monkeypatch):
    from datetime import datetime
    from sqlalchemy.orm import Session
    from types import SimpleNamespace
    from app.api.v1 import technique_history as api
    monkeypatch.setattr(api,'owner',lambda *args,**kwargs:SimpleNamespace(id=1))
    with pg.begin() as c:
        c.execute(text("INSERT INTO app_users VALUES(1); INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0)"))
        c.execute(text("""INSERT INTO dives(session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,dive_datetime)
        SELECT 1,1,'103','springboard','3','B',false,'G','2026-01-01'::timestamp + n * interval '1 day' FROM generate_series(1,30) n"""))
    def change(revision,day,label):return api.Change(code='103',scope='103',apparatus='springboard',height='3',position='B',revision=revision,start_at=datetime(2026,1,day),label=label)
    with Session(pg) as db:
        api.change(1,1,change(0,1,'Old A'),None,db)
        existing=api.change(1,1,change(1,10,'Saved B'),None,db)
        result=api.setup_preview(1,1,api.SetupPreview(changes=[change(2,5,'New C'),change(2,7,'New D'),change(2,15,'New E')]),None,db)
        assert [item['end_at'] for item in result['items']]==[datetime(2026,1,7),datetime(2026,1,10),None]
        assert [item['counts']['affected'] for item in result['items']]==[2,3,17]
        assert result['items'][1]['following']['id']==existing['episode']['id']
        assert result['items'][1]['following']['label']=='Saved B'
        assert result['items'][0]['next_label']=='New D'
        repeat=api.setup_preview(1,1,api.SetupPreview(changes=[change(2,5,'Old A'),change(2,7,'Saved B')]),None,db)
        assert repeat['items'][0]['same_previous'] is True
        assert repeat['items'][1]['same_following'] is True
        assert db.scalar(text('SELECT count(*) FROM technique_episodes'))==2
        assert db.scalar(text('SELECT revision FROM technique_tracks WHERE id=1'))==2


def test_setup_save_is_atomic_preserves_a_b_a_and_undo_reverts_the_whole_action(pg,monkeypatch):
    from sqlalchemy.orm import Session
    from types import SimpleNamespace
    from app.api.v1 import technique_history as api
    monkeypatch.setattr(api,'owner',lambda *args,**kwargs:SimpleNamespace(id=1))
    with pg.begin() as c:
        c.execute(text("INSERT INTO app_users VALUES(1); INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0)"))
    changes=[api.SetupChange(code='103',scope='103',apparatus='springboard',height='3',position='B',sync=False,constrain_position=True,constrain_sync=True,revision=0,start_at=f'2026-01-{day:02d}T00:00:00',draft_identity=key,label=key) for day,key in [(1,'A'),(2,'B'),(3,'A')]]
    with Session(pg) as db:
        result=api.setup_save(1,1,api.SetupSave(changes=changes),None,db)
        assert result['revision']==3
        a,b,again=result['episodes']
        assert a['technique_id']==again['technique_id']!=b['technique_id']
        assert all(e['sync'] is False for e in result['episodes'])
        assert db.scalar(text('SELECT count(*) FROM techniques'))==2
        api.undo(1,1,api.RevisionInput(revision=3),None,db)
        assert db.scalar(text('SELECT count(*) FROM technique_episodes WHERE NOT deleted'))==0


def test_setup_save_rolls_back_first_boundary_identity_and_audit_when_later_write_fails(pg,monkeypatch):
    from sqlalchemy.orm import Session
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.api.v1 import technique_history as api
    monkeypatch.setattr(api,'owner',lambda *args,**kwargs:SimpleNamespace(id=1))
    with pg.begin() as c:c.execute(text("INSERT INTO app_users VALUES(1); INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0)"))
    changes=[api.SetupChange(code='103',scope='103',apparatus='springboard',height='3',position='B',revision=0,start_at=f'2026-01-{day:02d}T00:00:00',label=key,draft_identity=key,technique_id=bad) for day,key,bad in [(1,'A',None),(2,'B',999)]]
    with Session(pg) as db:
        with pytest.raises(HTTPException):api.setup_save(1,1,api.SetupSave(changes=changes),None,db)
        assert db.scalar(text('SELECT revision FROM technique_tracks WHERE id=1'))==0
        for table in ('technique_episodes','techniques','technique_revisions'):
            assert db.scalar(text(f'SELECT count(*) FROM {table}'))==0

def test_session_browse_pages_full_history_and_filters_exact_context(pg,monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_history as api
    monkeypatch.setattr(api,'owner',lambda *a:SimpleNamespace(id=1))
    with pg.begin() as c:
        c.execute(text("""INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0);
        INSERT INTO sessions(id,location) SELECT n,'Pool' FROM generate_series(2,30) n;
        INSERT INTO dives(session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,dive_datetime)
        SELECT n,1,'103','springboard','3','B',false,'G',timestamp '2026-01-01'+n*interval '1 day' FROM generate_series(2,30) n;
        INSERT INTO dives(session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,dive_datetime)
        VALUES(30,1,'103','springboard','1','B',false,'P','2026-03-01'),(30,2,'103','springboard','3','B',false,'P','2026-03-01');"""))
    with Session(pg) as db:
        args=dict(code='103',apparatus='springboard',height='3',position='B',sync=False)
        first=api.browse_sessions(1,1,api.SessionBrowse(**args),None,db)
        assert len(first['items'])==24 and first['next']==7
        assert first['items'][0]['session_id']==30 and first['items'][0]['attempts']==1
        second=api.browse_sessions(1,1,api.SessionBrowse(**args,after=first['next']),None,db)
        assert [r['session_id'] for r in second['items']]==[6,5,4,3,2,1]
        assert second['next'] is None
        assert {r['session_id'] for r in first['items']}.isdisjoint(r['session_id'] for r in second['items'])
        assert first['months']==[{'month':'2026-01','sessions':30}]
        assert api.browse_sessions(1,1,api.SessionBrowse(**args,month='2026-02'),None,db)['items']==[]

def test_same_label_reuses_identity_without_merging_episodes(pg,monkeypatch):
    from types import SimpleNamespace
    from datetime import datetime
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_history as api
    monkeypatch.setattr(api,'owner',lambda *a:SimpleNamespace(id=1))
    with pg.begin() as c:c.execute(text("INSERT INTO app_users VALUES(1); INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0)"))
    with Session(pg) as db:
        def body(rev,day,label):return api.Change(code='103',scope='103',apparatus='springboard',height='3',position='B',revision=rev,start_at=datetime(2026,1,day),label=label)
        a=api.change(1,1,body(0,1,'Original'),None,db)
        api.change(1,1,body(1,2,'Later'),None,db)
        again=api.change(1,1,body(2,3,' original '),None,db)
        assert a['episode']['technique_id']==again['episode']['technique_id']
        assert a['episode']['id']!=again['episode']['id']
        assert db.scalar(text('SELECT count(*) FROM techniques'))==2

def test_independent_adjustments_overlap_replace_one_and_preserve_legacy(pg,monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_adjustments as api
    monkeypatch.setattr(api,'owner',lambda *a,**kw:SimpleNamespace(id=1))
    with pg.begin() as c:
        c.execute(text("INSERT INTO app_users VALUES(1); INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0); SELECT setval('technique_tracks_id_seq',1);"))
        c.execute(text("INSERT INTO dives(id,session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,dive_datetime) VALUES(2,1,1,'103','springboard','3','B',false,'G','2026-01-02'),(3,1,1,'103','springboard','3','B',false,'P','2026-01-03')"))
    args=dict(code='103',scope='103',apparatus='springboard',height='3',position='B',sync=False,revision=0,start_at='2026-01-01T00:00:00',precision='attempt')
    with Session(pg) as db:
        initial=api.revision(db,1)
        body=api.Batch(revision=initial,changes=[api.AdjustmentChange(**args,label='Less pike',anchor_id=1,draft_key='a'),api.AdjustmentChange(**args,label='Earlier twist',anchor_id=1,draft_key='b')])
        preview=api.preview(1,body,None,db)
        assert [i['end_at'] for i in preview['items']]==[None,None]
        assert all(i['counts']['affected']==3 for i in preview['items'])
        assert db.scalar(text('SELECT count(*) FROM technique_episodes'))==0
        saved=api.save(1,body,None,db);a,b=saved['episodes']
        assert a['track_id']!=b['track_id'] and a['end_at'] is None and b['end_at'] is None
        replaced=api.save(1,api.Batch(revision=saved['revision'],changes=[api.AdjustmentChange(**args,label='Deeper pike',anchor_id=2,draft_key='c',replace_episode_id=a['id'])]),None,db)
        assert db.scalar(text('SELECT end_at FROM technique_episodes WHERE id=:id'),{'id':a['id']}) is not None
        assert db.scalar(text('SELECT end_at FROM technique_episodes WHERE id=:id'),{'id':b['id']}) is None
        listing=api.listing(1,api.Browse(code='103',apparatus='springboard',height='3',position='B',sync=False),None,db)
        assert len(listing['items'])==3
        assert sum(e['end_at'] is None for e in listing['items'])==2
        delete=api.Remove(code='103',apparatus='springboard',height='3',position='B',sync=False,revision=listing['revision'],episode_id=replaced['episodes'][0]['id'])
        api.remove(1,delete,None,db)
        assert not db.scalar(text('SELECT deleted FROM technique_episodes WHERE id=:id'),{'id':delete.episode_id})
        delete.commit=True;api.remove(1,delete,None,db)
        assert db.scalar(text('SELECT deleted FROM technique_episodes WHERE id=:id'),{'id':delete.episode_id})
        assert db.scalar(text('SELECT end_at FROM technique_episodes WHERE id=:id'),{'id':b['id']}) is None
        with pytest.raises(Exception):api.save(1,body,None,db)
        db.rollback()

def test_independent_batch_replacement_and_atomic_rollback(pg,monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_adjustments as api
    monkeypatch.setattr(api,'owner',lambda *a,**kw:SimpleNamespace(id=1))
    with pg.begin() as c:
        c.execute(text("INSERT INTO app_users VALUES(1);INSERT INTO dives(id,session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,dive_datetime) VALUES(2,1,1,'103','springboard','3','B',false,'G','2026-01-02')"))
    args=dict(code='103',scope='103',apparatus='springboard',height='3',position='B',sync=False,revision=0,start_at='2026-01-01T00:00:00')
    with Session(pg) as db:
        batch=api.Batch(revision=0,changes=[api.AdjustmentChange(**args,label='A',anchor_id=1,draft_key='a'),api.AdjustmentChange(**args,label='B',anchor_id=2,draft_key='b',replace_draft_key='a')])
        p=api.preview(1,batch,None,db)
        assert p['items'][0]['end_at'] is not None and p['items'][1]['end_at'] is None
        original=api.record
        calls=[]
        def fail(*args):
            calls.append(1)
            if len(calls)==2:raise RuntimeError('second record failed')
            return original(*args)
        monkeypatch.setattr(api,'record',fail)
        with pytest.raises(RuntimeError):api.save(1,batch,None,db)
        assert db.scalar(text('SELECT count(*) FROM technique_tracks'))==0
        assert db.scalar(text('SELECT count(*) FROM technique_episodes'))==0
        monkeypatch.setattr(api,'record',original)
        result=api.save(1,batch,None,db)
        assert result['episodes'][0]['end_at'] is not None

def test_remove_legacy_end_is_explicit_and_keeps_other_adjustments_and_records(pg,monkeypatch):
    from types import SimpleNamespace
    from datetime import datetime
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_adjustments as api
    from app.api.v1 import technique_history as legacy
    monkeypatch.setattr(api,'owner',lambda *a,**kw:SimpleNamespace(id=1))
    monkeypatch.setattr(legacy,'owner',lambda *a,**kw:SimpleNamespace(id=1))
    with pg.begin() as c:c.execute(text("INSERT INTO app_users VALUES(1); INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0); SELECT setval('technique_tracks_id_seq',1)"))
    with Session(pg) as db:
        args=dict(code='103',scope='103',apparatus='springboard',height='3',position='B')
        a=legacy.change(1,1,legacy.Change(**args,revision=0,label='Pike',start_at=datetime(2025,1,1)),None,db)['episode']
        b=legacy.change(1,1,legacy.Change(**args,revision=1,label='Twist',start_at=datetime(2026,1,1)),None,db)['episode']
        db.execute(text("INSERT INTO technique_assignments(track_id,dive_id,diver_id,code,apparatus,height,position,sync,state,technique_id,episode_id) VALUES(1,1,1,'103','springboard','3','B',false,'technique',:tech,:episode)"),{'tech':a['technique_id'],'episode':a['id']});db.commit()
        # Two conflicting identities deliberately share a label: remap by ID.
        other=db.scalar(text("INSERT INTO techniques(track_id,label,created_at) VALUES(1,'Twist',now()) RETURNING id"))
        db.execute(text("""INSERT INTO dives(id,session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,dive_datetime)
          SELECT n,1,1,'103','springboard','3','B',false,'G','2025-06-01' FROM generate_series(2,6) n"""))
        db.execute(text("""INSERT INTO technique_assignments(track_id,dive_id,diver_id,code,apparatus,height,position,sync,state,technique_id,episode_id)
          VALUES(1,2,1,'103','springboard','3','B',false,'technique',:b,:episode),
          (1,3,1,'103','springboard','3','B',false,'technique',:other,:episode),
          (1,4,1,'103','springboard','3','B',false,'mixed',NULL,:episode),
          (1,5,1,'103','springboard','3','B',false,'unknown',NULL,:episode)"""),{'b':b['technique_id'],'other':other,'episode':a['id']})
        db.execute(text("""INSERT INTO technique_session_states(track_id,session_id,code,apparatus,height,position,sync,state)
          VALUES(1,1,'103','springboard','3','B',false,'mixed')"""));db.commit()
        context=dict(code='103',apparatus='springboard',height='3',position='B',sync=False)
        before=api.listing(1,api.Browse(**context),None,db)
        assert next(e for e in before['items'] if e['id']==a['id'])['end_at'] is not None
        body=api.End(**context,revision=before['revision'],episode_id=a['id'],resume=True)
        api.end(1,body,None,db)
        assert db.scalar(text('SELECT end_at FROM technique_episodes WHERE id=:id'),{'id':a['id']}) is not None
        body.commit=True;api.end(1,body,None,db)
        a_track=db.scalar(text('SELECT track_id FROM technique_episodes WHERE id=:id'),{'id':a['id']})
        assert a_track!=b['track_id']
        assert db.scalar(text('SELECT end_at FROM technique_episodes WHERE id=:id'),{'id':a['id']}) is None
        assert db.scalar(text('SELECT end_at FROM technique_episodes WHERE id=:id'),{'id':b['id']}) is None
        assert db.scalar(text('SELECT count(*) FROM technique_assignments WHERE track_id=:track AND episode_id=:id'),{'track':a_track,'id':a['id']})==5
        assert db.scalar(text('SELECT count(*) FROM technique_assignments WHERE track_id=1'))==5
        rows=db.execute(text(RESOLVED+' SELECT * FROM resolved ORDER BY id'),dict(context,diver=1,track=a_track)).mappings().all()
        assert [r['source'] for r in rows]==['recorded']*5+['session']
        assert [r['state'] for r in rows]==['technique']*3+['mixed','unknown','mixed']
        assert rows[0]['use_id']==rows[0]['intended_id']
        assert rows[1]['use_id']!=rows[1]['intended_id']
        assert rows[2]['use_id']!=rows[2]['intended_id']
        assert rows[1]['use_id']!=rows[2]['use_id']
        for r in rows[:3]:
            identity=db.execute(text('SELECT track_id,label FROM techniques WHERE id=:id'),{'id':r['use_id']}).one()
            assert identity.track_id==a_track
            assert identity.label==('Pike' if r['id']==1 else 'Twist')
        assert all(r['recorded_episode_id']==a['id'] for r in rows[:5])

def test_adjustment_inventory_is_paged_and_cannot_replace_another_divers_episode(pg,monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.orm import Session
    from fastapi import HTTPException
    from app.api.v1 import technique_adjustments as api
    monkeypatch.setattr(api,'owner',lambda *a,**kw:SimpleNamespace(id=1))
    with pg.begin() as c:
        c.execute(text("""INSERT INTO app_users VALUES(1); INSERT INTO divers VALUES(2);
        INSERT INTO technique_tracks(id,diver_id,name,revision) SELECT n,1,'adjustment-'||n,0 FROM generate_series(1,52) n;
        INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(100,2,'Private',0);
        INSERT INTO techniques(id,track_id,label,created_at) SELECT n,n,'Action '||n,now() FROM generate_series(1,52) n;
        INSERT INTO techniques(id,track_id,label,created_at) VALUES(100,100,'Private',now());
        INSERT INTO technique_episodes(id,track_id,technique_id,scope,apparatus,height,position,sync,start_at,start_id,precision,timezone,gap,notes,deleted)
        SELECT n,n,n,'103','springboard','3','B',false,'2025-01-01'::timestamp+n*interval '1 day',0,'date','UTC',false,'',false FROM generate_series(1,52) n;
        INSERT INTO technique_episodes(id,track_id,technique_id,scope,apparatus,height,position,sync,start_at,start_id,precision,timezone,gap,notes,deleted)
        VALUES(100,100,100,'103','springboard','3','B',false,'2025-01-01',0,'date','UTC',false,'',false);"""))
    with Session(pg) as db:
        args=dict(code='103',apparatus='springboard',height='3',position='B',sync=False)
        first=api.listing(1,api.Browse(**args),None,db)
        assert len(first['items'])==50 and first['next'] is not None
        second=api.listing(1,api.Browse(**args,after=first['next']),None,db)
        assert len(second['items'])==2 and second['next'] is None
        assert {e['id'] for e in first['items']}.isdisjoint(e['id'] for e in second['items'])
        bad=api.Batch(revision=first['revision'],changes=[api.AdjustmentChange(**args,scope='103',revision=0,start_at='2026-01-01T00:00:00',anchor_id=1,label='Bad',draft_key='a',replace_episode_id=100)])
        with pytest.raises(HTTPException) as error:api.save(1,bad,None,db)
        assert error.value.status_code==404
        assert db.scalar(text('SELECT count(*) FROM technique_episodes'))==53

def test_copying_adjustment_elsewhere_never_closes_others_or_duplicates_source_family(pg,monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_adjustments as api
    monkeypatch.setattr(api,'owner',lambda *a,**kw:SimpleNamespace(id=1))
    with pg.begin() as c:
        c.execute(text("INSERT INTO app_users VALUES(1); INSERT INTO dives(id,session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,dive_datetime) VALUES(2,1,1,'105','springboard','3','B',false,'G','2026-01-02')"))
    with Session(pg) as db:
        context=dict(code='103',apparatus='springboard',height='3',position='B',sync=False)
        source=api.save(1,api.Batch(revision=0,changes=[api.AdjustmentChange(**context,scope='103',revision=0,start_at='2025-01-01T00:00:00',label='Hurdle',draft_key='a')]),None,db)
        episode=source['episodes'][0]
        body=api.Copy(**context,revision=source['revision'],episode_id=episode['id'],targets=[dict(scope='1',apparatus='springboard',height='3')])
        api.copy(1,body,None,db)
        assert db.scalar(text('SELECT count(*) FROM technique_episodes'))==1
        body.commit=True;result=api.copy(1,body,None,db)
        copy=result['episodes'][0]
        assert copy['end_at'] is None and copy['track_id']!=episode['track_id']
        own=api.listing(1,api.Browse(**context),None,db)
        assert len(own['items'])==1
        other=api.listing(1,api.Browse(**dict(context,code='105')),None,db)
        assert len(other['items'])==1 and other['items'][0]['id']==copy['id']
        params=dict(context,diver=1,track=copy['track_id'])
        assert db.scalar(text(RESOLVED+' SELECT count(*) FROM resolved WHERE episode_id IS NOT NULL'),params)==0
        assert db.scalar(text(RESOLVED+' SELECT count(*) FROM resolved WHERE episode_id IS NOT NULL'),dict(params,code='105'))==1

def test_independent_duplicate_draft_adjustments_are_rejected_without_writes(pg,monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.orm import Session
    from fastapi import HTTPException
    from app.api.v1 import technique_adjustments as api
    monkeypatch.setattr(api,'owner',lambda *a,**kw:SimpleNamespace(id=1))
    context=dict(code='103',scope='103',apparatus='springboard',height='3',position='B',sync=False,revision=0,start_at='2026-01-01T00:00:00',anchor_id=1)
    with Session(pg) as db:
        batch=api.Batch(revision=0,changes=[api.AdjustmentChange(**context,label='Less pike',draft_key='a'),api.AdjustmentChange(**context,label=' less PIKE ',draft_key='b')])
        for action in [api.preview,api.save]:
            with pytest.raises(HTTPException) as failure:action(1,batch,None,db)
            assert failure.value.status_code==422
            db.rollback()
            assert db.scalar(text('SELECT count(*) FROM technique_episodes'))==0


def test_independent_stop_validation_stale_revision_and_sequential_resume(pg,monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.orm import Session
    from fastapi import HTTPException
    from app.api.v1 import technique_adjustments as api
    monkeypatch.setattr(api,'owner',lambda *a,**kw:SimpleNamespace(id=1))
    with pg.begin() as c:c.execute(text('INSERT INTO app_users VALUES(1)'))
    context=dict(code='103',apparatus='springboard',height='3',position='B',sync=False)
    with Session(pg) as db:
        result=api.save(1,api.Batch(revision=0,changes=[api.AdjustmentChange(**context,scope='103',revision=0,start_at='2026-01-01T00:00:00',anchor_id=1,label=label,draft_key=label) for label in ['A','B']]),None,db)
        current=result['revision']
        for episode in result['episodes']:
            for invalid in ['2025-12-31T00:00:00','2026-01-01T00:00:00']:
                with pytest.raises(HTTPException) as failure:api.end(1,api.End(**context,revision=current,episode_id=episode['id'],end_at=invalid,commit=True),None,db)
                assert failure.value.status_code==422
            stopped=api.end(1,api.End(**context,revision=current,episode_id=episode['id'],end_at='2026-02-01T12:00:00',timezone='Europe/Paris',commit=True),None,db)
            assert str(db.scalar(text('SELECT end_at FROM technique_episodes WHERE id=:id'),{'id':episode['id']}))=='2026-02-01 11:00:00'
            with pytest.raises(HTTPException) as failure:api.end(1,api.End(**context,revision=current,episode_id=episode['id'],resume=True,commit=True),None,db)
            assert failure.value.status_code==409
            resumed=api.end(1,api.End(**context,revision=stopped['revision'],episode_id=episode['id'],resume=True,commit=True),None,db)
            current=resumed['revision']
        assert db.scalar(text('SELECT count(*) FROM technique_episodes WHERE end_at IS NULL'))==2


def test_track_names_cannot_shadow_internal_adjustment_prefix(pg,monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.orm import Session
    from fastapi import HTTPException
    from app.api.v1 import technique_history as api
    monkeypatch.setattr(api,'owner',lambda *a,**kw:SimpleNamespace(id=1))
    with Session(pg) as db:
        for reserved in ('adjustment-foo','adjustment-copy-foo'):
            with pytest.raises(HTTPException) as failure:
                api.create_track(1,api.TrackInput(name=reserved),None,db)
            assert failure.value.status_code==422
            db.rollback()
        track=api.create_track(1,api.TrackInput(name='General'),None,db)
        assert track['name']=='General'
        assert db.scalar(text('SELECT count(*) FROM technique_tracks'))==1


def test_technique_ratings_use_the_shared_nullable_scoring_expression(pg):
    from app.services.performance_scoring import recorded_score_10_expression
    from app.models.dive import Dive
    from sqlalchemy import select
    with pg.begin() as c:
        c.execute(text("INSERT INTO dives(id,session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,phase1_performance,phase2_performance,dive_datetime) SELECT row_number() OVER()+1,1,1,'103','springboard','3','B',false,'G',a,b,'2026-01-01' FROM unnest(ARRAY['F','B','M','G','P']) a CROSS JOIN unnest(ARRAY['F','B','M','G','P']) b"))
        c.execute(text("INSERT INTO dives(id,session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,phase1_performance,phase2_performance,dive_datetime) VALUES(100,1,1,'103','springboard','3','B',false,NULL,'g','p','2026-01-01'),(101,1,1,'103','springboard','3','B',false,'m','unknown','G','2026-01-01')"))
        expected=dict(c.execute(select(Dive.id,recorded_score_10_expression())).all())
        actual=dict(c.execute(text(RESOLVED+' SELECT id,rating FROM resolved'),dict(diver=1,track=0,code='103',apparatus='springboard',height='3',position='B',sync=False)).all())
        assert actual.keys()==expected.keys()
        for key,value in expected.items():assert float(actual[key])==pytest.approx(float(value)) if value is not None else actual[key] is None


def test_session_browser_paginates_month_inventory_beyond_ten_years(pg,monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.orm import Session
    from app.api.v1 import technique_history as api
    monkeypatch.setattr(api,'owner',lambda *a,**kw:SimpleNamespace(id=1))
    with pg.begin() as c:
        c.execute(text("INSERT INTO technique_tracks(id,diver_id,name,revision) VALUES(1,1,'General',0); INSERT INTO sessions(id) SELECT n FROM generate_series(2,122) n; INSERT INTO dives(id,session_id,diver_id,dive_code,platform_type,height,position,is_sync,performance,dive_datetime) SELECT n,n,1,'103','springboard','3','B',false,'G','2000-01-01'::timestamp+n*interval '1 month' FROM generate_series(2,122) n"))
    with Session(pg) as db:
        args=dict(code='103',apparatus='springboard',height='3',position='B',sync=False)
        first=api.browse_sessions(1,1,api.SessionBrowse(**args),None,db)
        assert len(first['months'])==120 and first['months_next']
        second=api.browse_sessions(1,1,api.SessionBrowse(**args,months_after=first['months_next']),None,db)
        assert len(second['months'])==2 and second['months_next'] is None
        assert len({m['month'] for m in first['months']+second['months']})==122
        oldest=second['months'][-1]['month']
        filtered=api.browse_sessions(1,1,api.SessionBrowse(**args,month=oldest),None,db)
        assert len(filtered['items'])==1 and filtered['items'][0]['first_at'].strftime('%Y-%m')==oldest
