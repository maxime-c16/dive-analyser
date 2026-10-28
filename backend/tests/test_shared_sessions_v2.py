from fastapi.testclient import TestClient
import pytest
from app.main import app
from app.models.session_video import SessionVideo, SessionSignupReview
from app.models.calendar import Club, TrainingGroup, TrainingGroupMembership
from app.models.diver import Diver
from app.models.user_auth import AppUser, UserDiverAccess
from app.services import session_videos as service
from tests.test_session_videos import sessions_env, KEY
from tests.test_member_dive_visibility import workspace


def link(owner, video):
    video_id = video if isinstance(video, int) else video.id
    path=owner.post(f'/api/v1/session-videos/{video_id}/shares').json()['path']
    sid,token=path.split('/')[-1].split('#')
    return f'/api/v1/shared-dives/sessions/{sid}',token


def test_later_videos_and_owner_settings(sessions_env):
    db,login,users,b2,_=sessions_env
    first=service.ingest_object(db,KEY);first_id=first.id;owner=login('alice');base,token=link(owner,first_id)
    b2.objects['inbox/second.MOV']=3338404955
    second=service.ingest_object(db,'inbox/second.MOV')
    second_id=second.id
    with TestClient(app,base_url='https://testserver') as guest:
        result=guest.post(base+'/visit',headers={'X-Dive-Share':token}).json()
        assert {v['id'] for v in result['videos']}=={first_id,second_id}
        assert result['video_count']==2
        assert guest.get(base+'/download',follow_redirects=False).status_code==401
        assert guest.get(f'{base}/videos/{second_id}/play',follow_redirects=False).status_code==302
        assert owner.patch(f'/api/v1/session-videos/{second_id}',json={'hidden':True}).status_code==200
        assert guest.get(f'{base}/videos/{second_id}/play').status_code==404
        assert owner.patch(f'/api/v1/session-videos/{second_id}',json={'hidden':False,'date':'2026-10-18'}).status_code==200
        assert guest.get(f'{base}/videos/{second_id}/play').status_code==404
        assert owner.patch(f'/api/v1/session-videos/{first_id}',json={'delete':True}).status_code==200
        # The anchor recording is gone from the app: the link no longer opens.
        assert guest.post(base+'/visit',headers={'X-Dive-Share':token}).status_code==404
    friend=login('viewer')
    assert friend.patch(f'/api/v1/session-videos/{second_id}',json={'hidden':True}).status_code==403
    feed=friend.get('/api/v1/shared-sessions').json()
    assert feed['items'] and feed['items'][0]['videos'], (feed, [(v.id,v.session_id,v.hidden,v.deleted_at,v.status) for v in db.query(SessionVideo).all()])
    assert feed['items'][0]['videos'][0]['can_share'] is False


def test_signup_group_profile_review_and_revoke(sessions_env):
    db,login,users,*_=sessions_env
    video=service.ingest_object(db,KEY);video_id=video.id;admin_id=users['alice'].id;owner=login('alice');base,token=link(owner,video_id)
    club=Club(slug='test',name='Test',self_join_enabled=True);db.add(club);db.flush()
    group=TrainingGroup(club_id=club.id,slug='adults',name='Adultes');db.add(group)
    db.add(Diver(display_name='MAT',canonical_name='mat'));db.commit()
    group_id=group.id
    with TestClient(app,base_url='https://testserver') as guest:
        guest.post(base+'/visit',headers={'X-Dive-Share':token})
        assert guest.get(base+'/groups').json()['items'][0]['id']==group_id
        payload=dict(display_name='Mat',email='mat@example.test',password='a-long-test-password',group_id=group_id)
        result=guest.post(base+'/signup',json=payload)
        assert result.status_code==201,result.text
        user=db.query(AppUser).filter_by(email=payload['email']).one()
        assert user.role=='diver' and user.session_email_enabled
        assert db.query(TrainingGroupMembership).filter_by(user_id=user.id,group_id=group_id).count()==1
        assert db.query(Diver).filter_by(canonical_name='mat').count()==1
        user_id=user.id
        review=db.query(SessionSignupReview).filter_by(user_id=user.id).one()
        assert db.query(UserDiverAccess).filter_by(user_id=user.id).count()==0
        review_id=review.id
        assert guest.put('/api/v1/session-preferences',json={'enabled':False}).status_code==200
        assert guest.get('/api/v1/session-preferences').json()=={'enabled':False}
        admin=db.get(AppUser,admin_id);admin.is_admin=True;db.commit()
        assert owner.post(f'/api/v1/session-signup-reviews/{review_id}/accept').status_code==200
        assert db.query(UserDiverAccess).filter_by(user_id=user_id).count()==1
        assert owner.delete(f'/api/v1/session-videos/{video_id}/shares').status_code==204
        assert guest.post(base+'/signup',json={**payload,'email':'other@example.test'}).status_code==404
    with TestClient(app,base_url='https://testserver') as guest:
        base,token=link(owner,video_id);guest.post(base+'/visit',headers={'X-Dive-Share':token})
        assert guest.post(base+'/signup',json={**payload,'display_name':'New Diver','email':'new@example.test'}).status_code==201
        new=db.query(AppUser).filter_by(email='new@example.test').one()
        assert new.role=='diver' and db.query(UserDiverAccess).filter_by(user_id=new.id).count()==1


def test_range_source_never_reads_full_response(monkeypatch):
    import requests
    from app.services.session_images import range_source,RANGE_BYTES
    seen=[]
    class Upstream:
        status_code=200
        headers={'Content-Length':'3338404955'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,*args):raise AssertionError('must not consume full response')
    original=requests.get
    def upstream(url,**kwargs):seen.append(kwargs['headers']['Range']);return Upstream()
    monkeypatch.setattr('app.services.session_images.requests.get',upstream)
    with range_source('https://private.test/source') as (url,stats):
        assert original(url,headers={'Range':'bytes=0-'}).status_code==502
        assert seen==[f'bytes=0-{RANGE_BYTES-1}']
        assert stats['bytes']==RANGE_BYTES


def test_feed_has_fixed_query_budget_and_complete_totals(sessions_env):
    from sqlalchemy import event
    from app.api.v1.session_videos import session_feed, session_payload
    from fastapi import Response
    from app.models.session import Session as TrainingSession
    from datetime import date
    db, login, users, *_ = sessions_env
    user=db.get(AppUser,users['alice'].id)
    for day in range(1,23):
        training=TrainingSession(date=date(2026,9,day));db.add(training);db.flush()
        for index in range(3):
            db.add(SessionVideo(session_id=training.id,owner_user_id=user.id,bucket='test',object_key=f'{day}/{index}',status='ready',duration_seconds=10,size_bytes=100))
    db.commit()
    queries=[]
    def count(conn,cursor,statement,*args):queries.append(statement)
    event.listen(db.bind,'before_cursor_execute',count)
    try:
        result=session_feed(Response(),None,user,db)
    finally:event.remove(db.bind,'before_cursor_execute',count)
    assert len(result['items'])==20 and result['next_cursor']
    assert len(queries)<=6
    assert all(s['video_count']==3 and s['total_duration']==30 and s['total_bytes']==300 for s in result['items'])
    page2=session_feed(Response(),result['next_cursor'],user,db)
    assert len(page2['items'])==2
    assert not {s['session_id'] for s in page2['items']} & {s['session_id'] for s in result['items']}
    target=result['items'][0]['session_id']
    for index in range(105):db.add(SessionVideo(session_id=target,owner_user_id=user.id,bucket='test',object_key=f'extra/{index}',status='ready',duration_seconds=10,size_bytes=100))
    db.commit()
    first=session_payload(db,target,user=user)
    assert len(first['videos'])==100 and first['video_count']==108 and first['total_duration']==1080
    second=session_payload(db,target,user=user,after=first['next_video_id'])
    assert len(second['videos'])==8 and second['next_video_id'] is None


def test_owner_totals_include_hidden_viewer_totals_exclude(sessions_env):
    db,login,users,b2,*_=sessions_env
    first=service.ingest_object(db,KEY)
    b2.objects['inbox/second.MOV']=3338404955
    second=service.ingest_object(db,'inbox/second.MOV')
    sid=first.session_id
    assert second.session_id==sid
    owner=login('alice')
    assert owner.patch(f'/api/v1/session-videos/{second.id}',json={'hidden':True}).status_code==200
    detail=owner.get(f'/api/v1/shared-sessions/{sid}').json()
    assert len(detail['videos'])==2 and detail['video_count']==2
    seen=login('viewer').get(f'/api/v1/shared-sessions/{sid}').json()
    assert len(seen['videos'])==1 and seen['video_count']==1


def test_hidden_session_detail_is_private_but_manageable(sessions_env):
    db,login,users,*_=sessions_env
    video=service.ingest_object(db,KEY)
    sid=video.session_id
    owner=login('alice')
    assert owner.patch(f'/api/v1/session-videos/{video.id}',json={'hidden':True}).status_code==200
    assert login('viewer').get(f'/api/v1/shared-sessions/{sid}').status_code==404
    # The cursor does not bypass the privacy check.
    assert login('viewer').get(f'/api/v1/shared-sessions/{sid}',params={'after':video.id}).status_code==404
    owner = login('alice')  # login() shares one client: reset the cookie viewer replaced
    detail=owner.get(f'/api/v1/shared-sessions/{sid}')
    assert detail.status_code==200 and len(detail.json()['videos'])==1
    assert owner.get(f'/api/v1/shared-sessions/{sid}',params={'after':video.id}).status_code==200


def test_calendar_session_still_notifies_owner(sessions_env, monkeypatch):
    from datetime import date, datetime
    from app.config import get_settings
    from app.models.calendar import Calendar, CalendarEvent, Club, EventOccurrence
    from app.models.notification import Notification
    from app.models.session import Session as TrainingSession
    monkeypatch.setattr(get_settings(), 'calendar_enabled', True)
    db, login, users, *_ = sessions_env
    club = Club(slug='ownercal', name='OwnerCal'); db.add(club); db.flush()
    cal = Calendar(kind='club', club_id=club.id, name='OwnerCal'); db.add(cal); db.flush()
    event = CalendarEvent(calendar_id=cal.id, title='Training', event_type='training', audience='club',
        status='published', timezone='Europe/Paris'); db.add(event); db.flush()
    occ = EventOccurrence(event_id=event.id, occurrence_key='o1', starts_at=datetime(2026, 10, 17, 11),
        ends_at=datetime(2026, 10, 17, 13), window_start=datetime(2026, 10, 17, 11),
        window_end=datetime(2026, 10, 17, 13)); db.add(occ); db.flush()
    training = TrainingSession(date=date(2026, 10, 17), calendar_occurrence_id=occ.id); db.add(training); db.flush()
    video = SessionVideo(session_id=training.id, owner_user_id=users['alice'].id, bucket='test',
        object_key='inbox/owner.MOV', status='ready'); db.add(video); db.flush(); db.commit()
    service._notify_once(db, video.id)
    owner_rows = db.query(Notification).filter_by(user_id=users['alice'].id, type='session_video').all()
    assert len(owner_rows) == 1 and owner_rows[0].session_id is None
    assert db.get(TrainingSession, training.id).calendar_notified_at is not None


def test_signup_groups_paginate(sessions_env):
    db,login,users,*_=sessions_env
    video=service.ingest_object(db,KEY);video_id=video.id;owner=login('alice');base,token=link(owner,video_id)
    club=Club(slug='manygroups',name='Many',self_join_enabled=True);db.add(club);db.flush()
    for index in range(101):
        db.add(TrainingGroup(club_id=club.id,slug=f'g{index}',name=f'G{index:03}'))
    db.commit()
    with TestClient(app,base_url='https://testserver') as guest:
        guest.post(base+'/visit',headers={'X-Dive-Share':token})
        first=guest.get(base+'/groups').json()
        assert len(first['items'])==100 and first['next_after']
        cursor=first['next_after']
        second=guest.get(base+'/groups',params={'after_club':cursor['club'],'after_group':cursor['group'],'after_id':cursor['id']}).json()
        assert len(second['items'])==1 and second['next_after'] is None
        assert {g['id'] for g in first['items']} | {g['id'] for g in second['items']} == {g.id for g in db.query(TrainingGroup).all()}


def test_signup_uses_club_timezone_for_effective_date(sessions_env, monkeypatch):
    from app.api.v1 import session_videos as api
    from app.models.calendar import TrainingGroupMembership
    from datetime import date
    db,login,users,*_=sessions_env
    video=service.ingest_object(db,KEY);video_id=video.id;owner=login('alice');base,token=link(owner,video_id)
    club=Club(slug='tzclub',name='Tz',self_join_enabled=True,timezone='Pacific/Kiritimati');db.add(club);db.flush()
    group=TrainingGroup(club_id=club.id,slug='tzg',name='TzG');db.add(group);db.commit()
    group_id=group.id
    monkeypatch.setattr(api,'club_today',lambda club: date(2030,2,3))
    with TestClient(app,base_url='https://testserver') as guest:
        guest.post(base+'/visit',headers={'X-Dive-Share':token})
        payload=dict(display_name='Tz Diver',email='tz@example.test',password='a-long-test-password',group_id=group_id)
        assert guest.post(base+'/signup',json=payload).status_code==201
    membership=db.query(TrainingGroupMembership).filter_by(group_id=group_id).one()
    assert membership.effective_from==date(2030,2,3)


def test_group_fanout_is_capped_and_resumes(sessions_env, monkeypatch):
    from tests.test_session_calendar import setup_group
    import app.services.session_calendar as calendar
    from app.models.notification import Notification
    from app.models.session import Session as TrainingSession
    from datetime import date
    monkeypatch.setattr(calendar,'_NOTIFY_BATCH_SIZE',2)
    monkeypatch.setattr(calendar,'_NOTIFY_MAX_BATCHES',1)
    db,login,users,*_=sessions_env
    occ=setup_group(db,users)
    training=TrainingSession(date=date(2026,10,17),calendar_occurrence_id=occ.id);db.add(training);db.flush()
    video=SessionVideo(session_id=training.id,owner_user_id=users['alice'].id,bucket='test',object_key='inbox/cap.MOV',status='ready')
    db.add(video);db.flush();db.commit()
    assert calendar.notify_session(db,video) is True
    assert db.query(Notification).filter_by(session_id=training.id).count()==2
    assert db.get(TrainingSession,training.id).calendar_notified_at is None
    service._resume_pending_session_notifications(db)
    assert db.query(Notification).filter_by(session_id=training.id).count()==3
    assert db.get(TrainingSession,training.id).calendar_notified_at is not None


def test_owner_alert_has_no_preference_toggle(sessions_env):
    from app.models.notification import NotificationPref
    from app.services import notification_service
    db,login,users,*_=sessions_env
    client=login('alice')
    assert client.put('/api/v1/notification-prefs',json={'type':'session_video','enabled':False}).status_code==422
    assert 'session_video' not in client.get('/api/v1/notification-prefs').json()['prefs']
    db.add(NotificationPref(user_id=users['alice'].id,notif_type='session_video',enabled=False));db.commit()
    assert notification_service.is_enabled(db,users['alice'].id,'session_video') is True


def test_signup_review_queue_paginates(sessions_env):
    from app.models.diver import Diver
    from app.models.session_video import SessionSignupReview
    db,login,users,*_=sessions_env
    for index in range(101):
        user=AppUser(email=f'review{index}@example.test',display_name=f'Review {index}',role='diver')
        db.add(user);db.flush()
        diver=Diver(display_name=f'Candidat {index}',canonical_name=f'review-candidate-{index}')
        db.add(diver);db.flush()
        db.add(SessionSignupReview(user_id=user.id,candidate_diver_id=diver.id))
    db.get(AppUser,users['alice'].id).is_admin=True;db.commit()
    admin=login('alice')
    first=admin.get('/api/v1/session-signup-reviews').json()
    assert len(first['items'])==100 and first['next_after']
    second=admin.get('/api/v1/session-signup-reviews',params={'after':first['next_after']}).json()
    assert len(second['items'])==1 and second['next_after'] is None
    assert {r['id'] for r in first['items']} | {r['id'] for r in second['items']} == {r.id for r in db.query(SessionSignupReview).all()}


def test_session_image_cleanup_rotates_scan(sessions_env,tmp_path,monkeypatch):
    from app.config import get_settings
    from app.models.session import Session as TrainingSession
    from app.models.user_auth import AppUser
    from app.services.session_images import cleanup_session_images, image_path
    import app.services.session_images as images
    import os as _os
    from pathlib import Path as _Path
    from datetime import date, datetime
    monkeypatch.setattr(get_settings(),'media_cache_root',str(tmp_path))
    images._scan_cursor=None
    try:
        db,login,users,*_=sessions_env
        user=db.get(AppUser,users['alice'].id)
        for index in range(3):
            training=TrainingSession(date=date(2026,10,10+index));db.add(training);db.flush()
            video=SessionVideo(session_id=training.id,owner_user_id=user.id,bucket='test',object_key=f'rot{index}.MOV',status='ready',deleted_at=datetime.utcnow())
            db.add(video);db.flush()
            for kind in ('poster','animated'):
                path=image_path(video.id,kind);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'x'*100)
        db.commit()
        stale=image_path(424242,'poster').parent
        stale.mkdir(parents=True,exist_ok=True)
        _os.utime(stale,(0,0))
        assert cleanup_session_images(db,shard_budget=1)==200
        assert cleanup_session_images(db,shard_budget=1)==200
        assert cleanup_session_images(db,shard_budget=1)==200
        assert cleanup_session_images(db,shard_budget=1)==0
        assert not stale.exists()
        assert cleanup_session_images(db,shard_budget=1)==0
    finally:
        images._scan_cursor=None


def test_session_image_publish_respects_disk_budget(tmp_path,monkeypatch):
    from app.config import get_settings
    from app.services import session_images as images
    monkeypatch.setattr(get_settings(),'media_cache_root',str(tmp_path))
    target=images.image_path(7,'poster').parent;target.mkdir(parents=True)
    (target/'poster.webp').write_bytes(b'o'*100)
    staged={}
    for kind in ('poster','animated'):
        p=target/f'{kind}.1.tmp';p.write_bytes(b'n'*100);staged[kind]=p
    monkeypatch.setattr(images,'SESSION_IMAGES_MAX_BYTES',150)
    with pytest.raises(RuntimeError):
        images.publish_images(target,staged)
    assert (target/'poster.webp').read_bytes()==b'o'*100
    assert not (target/'poster.1.tmp').exists() and not (target/'animated.1.tmp').exists()
    staged={}
    for kind in ('poster','animated'):
        p=target/f'{kind}.2.tmp';p.write_bytes(b'n'*100);staged[kind]=p
    monkeypatch.setattr(images,'SESSION_IMAGES_MAX_BYTES',1000)
    images.publish_images(target,staged)
    assert (target/'poster.webp').read_bytes()==b'n'*100 and (target/'animated.webp').read_bytes()==b'n'*100


def test_successful_signup_consumes_no_failure_budget(sessions_env):
    from app.api.v1 import auth
    from app.models.user_auth import LoginAttempt
    db,login,users,*_=sessions_env
    video=service.ingest_object(db,KEY);video_id=video.id;owner=login('alice');base,token=link(owner,video_id)
    club=Club(slug='ledger',name='Ledger',self_join_enabled=True);db.add(club);db.flush()
    group=TrainingGroup(club_id=club.id,slug='g',name='G');db.add(group);db.commit()
    payload=dict(display_name='Ledger Diver',email='ledger@example.test',password='a-long-test-password',group_id=group.id)
    with TestClient(app,base_url='https://testserver') as guest:
        guest.post(base+'/visit',headers={'X-Dive-Share':token})
        assert guest.post(base+'/signup',json=payload).status_code==201
        failures=db.query(LoginAttempt).filter_by(identifier=auth._REGISTER_IDENTIFIER,success=False).count()
        assert failures==0
        assert guest.post(base+'/signup',json={**payload,'display_name':'Other'}).status_code==409
        failures=db.query(LoginAttempt).filter_by(identifier=auth._REGISTER_IDENTIFIER,success=False).count()
        assert failures==1


def test_feed_pagination_keeps_same_day_sessions(sessions_env):
    # Two trainings on one date (PR C): same-day sessions past a page boundary
    # must not be skipped by the cursor.
    from fastapi import Response
    from datetime import datetime
    from app.api.v1.session_videos import session_feed
    from app.models.session import Session as TrainingSession
    from app.models.calendar import Calendar, CalendarEvent, EventOccurrence
    from datetime import date
    db,login,users,*_=sessions_env
    user=db.get(AppUser,users['alice'].id)
    club=Club(slug='pageday',name='Pageday');db.add(club);db.flush()
    group=TrainingGroup(club_id=club.id,slug='g',name='G');db.add(group);db.flush()
    cal=Calendar(kind='group',club_id=club.id,training_group_id=group.id,name='Pageday');db.add(cal);db.flush()
    event=CalendarEvent(calendar_id=cal.id,title='Training',event_type='training',audience='group',
        status='published',timezone='Europe/Paris');db.add(event);db.flush()
    day=date(2026,10,17)
    for index in range(22):
        occ=EventOccurrence(event_id=event.id,occurrence_key=f'slot{index}',starts_at=datetime(2026,10,17,8,0),
            ends_at=datetime(2026,10,17,9,0),window_start=datetime(2026,10,17,8,0),window_end=datetime(2026,10,17,9,0))
        db.add(occ);db.flush()
        training=TrainingSession(date=day,calendar_occurrence_id=occ.id);db.add(training);db.flush()
        db.add(SessionVideo(session_id=training.id,owner_user_id=user.id,bucket='test',object_key=f'sameday/{index}',status='ready'))
    db.commit()
    first=session_feed(Response(),None,user,db)
    assert len(first['items'])==20 and first['next_cursor']
    second=session_feed(Response(),first['next_cursor'],user,db)
    assert len(second['items'])==2 and not second['next_cursor']
    seen=[s['session_id'] for s in first['items']]+[s['session_id'] for s in second['items']]
    assert len(set(seen))==22


def test_session_image_cleanup_removes_only_dead_videos(sessions_env,tmp_path,monkeypatch):
    from datetime import datetime
    from app.models.session import Session as TrainingSession
    from app.models.user_auth import AppUser
    from app.services.session_images import cleanup_session_images, image_path
    from app.config import get_settings
    from datetime import date
    monkeypatch.setattr(get_settings(),'media_cache_root',str(tmp_path))
    db,login,users,*_=sessions_env
    user=db.get(AppUser,users['alice'].id)
    live_training=TrainingSession(date=date(2026,10,17));db.add(live_training);db.flush()
    live=SessionVideo(session_id=live_training.id,owner_user_id=user.id,bucket='test',object_key='live.MOV',status='ready')
    dead_training=TrainingSession(date=date(2026,10,16));db.add(dead_training);db.flush()
    dead=SessionVideo(session_id=dead_training.id,owner_user_id=user.id,bucket='test',object_key='dead.MOV',status='ready',deleted_at=datetime.utcnow())
    db.add_all([live,dead]);db.flush()
    for video in (live,dead):
        for kind in ('poster','animated'):
            path=image_path(video.id,kind);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'x'*100)
    ghost=image_path(999999,'poster');ghost.parent.mkdir(parents=True,exist_ok=True);ghost.write_bytes(b'y'*50)
    from sqlalchemy import event
    queries=[]
    def count(conn,cursor,statement,*args):queries.append(statement)
    event.listen(db.bind,'before_cursor_execute',count)
    try:
        freed=cleanup_session_images(db)
    finally:event.remove(db.bind,'before_cursor_execute',count)
    assert freed==250
    assert len(queries)<=1
    assert image_path(live.id,'poster').is_file() and image_path(live.id,'animated').is_file()
    assert not image_path(dead.id,'poster').exists() and not image_path(dead.id,'animated').exists()
    assert not ghost.exists()
