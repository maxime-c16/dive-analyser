from fastapi.testclient import TestClient
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
        assert guest.post(base+'/visit',headers={'X-Dive-Share':token}).status_code==200
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
        assert guest.get(base+'/groups').json()[0]['id']==group_id
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
