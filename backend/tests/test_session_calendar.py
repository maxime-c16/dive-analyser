from datetime import date, datetime, timedelta

from app.config import get_settings
from app.models.calendar import (Club, ClubMembership, TrainingGroup, TrainingGroupMembership, Calendar,
    CalendarEvent, EventOccurrence, OccurrenceInterest, OccurrenceAbsenceReport)
from app.models.notification import Notification
from app.models.session import Session as TrainingSession
from app.services import session_calendar as calendar, session_videos as service
from tests.test_session_videos import sessions_env, KEY, PROBE
from tests.test_member_dive_visibility import workspace


def setup_group(db, users):
    club = Club(slug='calendar', name='Club calendrier')
    db.add(club); db.flush()
    group = TrainingGroup(club_id=club.id, slug='adultes', name='Adultes')
    db.add(group); db.flush()
    for user in users.values():
        m = ClubMembership(club_id=club.id, user_id=user.id, source='manager', started_at=datetime(2026, 1, 1))
        db.add(m); db.flush()
        db.add(TrainingGroupMembership(club_id=club.id, group_id=group.id, club_membership_id=m.id,
            user_id=user.id, effective_from=date(2026, 1, 1)))
    cal = Calendar(kind='group', club_id=club.id, training_group_id=group.id, name='Adultes')
    db.add(cal); db.flush()
    e = CalendarEvent(calendar_id=cal.id, title='Entraînement', event_type='training', audience='group',
        status='published', timezone='Europe/Paris', venue_name='Montreuil')
    db.add(e); db.flush()
    o = EventOccurrence(event_id=e.id, occurrence_key='oct17', starts_at=datetime(2026, 10, 17, 11),
        ends_at=datetime(2026, 10, 17, 13), window_start=datetime(2026, 10, 17, 11), window_end=datetime(2026, 10, 17, 13))
    db.add(o); db.commit()
    return o


def test_attendance_absence_and_withdrawal(sessions_env, monkeypatch):
    db, login, users, *_ = sessions_env
    monkeypatch.setattr(get_settings(), 'calendar_enabled', True)
    o = setup_group(db, users); oid = o.id
    # Old positive responses survive and have no effect on default attendance.
    db.add(OccurrenceInterest(occurrence_id=oid, user_id=users['bob'].id, state='maybe')); db.commit()
    client = login('alice')
    url = f'/api/v1/calendar/occurrences/{oid}'
    assert client.get(url).json()['going']['interested'] == 3
    absent = client.put(url+'/absence', json={'absent': True})
    assert absent.status_code == 200, absent.text
    assert absent.json()['my_absence_reported'] and absent.json()['going']['interested'] == 2
    restored = client.put(url+'/absence', json={'absent': False}).json()
    assert not restored['my_absence_reported'] and restored['going']['interested'] == 3
    assert db.get(OccurrenceInterest, (oid, users['bob'].id)).state == 'maybe'
    db.add(OccurrenceInterest(occurrence_id=oid, user_id=users['alice'].id, state='declined')); db.commit()
    assert client.get(url).json()['my_absence_reported']
    assert not client.put(url+'/absence', json={'absent': False}).json()['my_absence_reported']


def test_ingest_window_two_trainings_and_fallback(sessions_env, monkeypatch):
    db, _, users, b2, _ = sessions_env
    monkeypatch.setattr(get_settings(), 'calendar_enabled', True)
    o = setup_group(db, users)
    first = service.ingest_object(db, KEY); first_id, sid = first.id, first.session_id
    assert db.get(TrainingSession, sid).calendar_occurrence_id == o.id
    assert calendar.session_titles(db, [o.id])[o.id] == 'Entraînement sam. 13h · Montreuil'
    # Margin applies; a time outside the margin stays on the fallback day.
    assert calendar.matching_occurrence(db, datetime(2026, 10, 17, 10, 40)).id == o.id
    assert calendar.matching_occurrence(db, datetime(2026, 10, 17, 10, 29)) is None
    assert calendar.matching_occurrence(db, datetime(2026, 10, 17, 13, 30)) is None
    o2 = EventOccurrence(event_id=o.event_id, occurrence_key='evening', starts_at=datetime(2026, 10, 17, 16),
        ends_at=datetime(2026, 10, 17, 18), window_start=datetime(2026, 10, 17, 16), window_end=datetime(2026, 10, 17, 18))
    db.add(o2); db.commit()
    import copy
    def ingest(key, when):
        b2.objects[key] = 100
        probe = copy.deepcopy(PROBE)
        probe['format']['tags']['com.apple.quicktime.creationdate'] = when
        monkeypatch.setattr(service, 'run_ffprobe', lambda _: probe)
        return service.ingest_object(db, key).session_id
    assert ingest('inbox/second.MOV', '2026-10-17T13:15:00+0200') == sid
    second_sid = ingest('inbox/evening.MOV', '2026-10-17T18:05:00+0200')
    fallback_sid = ingest('inbox/late.MOV', '2026-10-17T23:05:00+0200')
    assert len({sid, second_sid, fallback_sid}) == 3
    assert db.get(TrainingSession, fallback_sid).calendar_occurrence_id is None
    assert db.get(EventOccurrence, o2.id).filmed_session_id == second_sid
    assert ingest('inbox/late2.MOV', '2026-10-17T23:15:00+0200') == fallback_sid


def test_first_video_notifies_non_absent_once_all_transports(sessions_env, monkeypatch):
    db, login, users, b2, _ = sessions_env
    monkeypatch.setattr(get_settings(), 'calendar_enabled', True)
    o = setup_group(db, users)
    absent_id = users['viewer'].id
    db.add(OccurrenceAbsenceReport(occurrence_id=o.id, user_id=absent_id))
    db.get(type(users['bob']), users['bob'].id).session_email_enabled = False
    db.commit()
    pushes, emails = [], []
    def push(db, rows):
        pushes.extend((r.user_id, r._push_payload['url']) for r in rows)
    monkeypatch.setattr('app.services.push_service.fanout_for_rows', push)
    monkeypatch.setattr('app.services.email_service.is_email_configured', lambda: True)
    monkeypatch.setattr('app.services.email_service.send_message', lambda msg, address: emails.append((address, msg.get_content())) or (True, ''))
    video = service.ingest_object(db, KEY)
    sid = video.session_id
    service.ingest_object(db, KEY)
    b2.objects['inbox/second.MOV'] = 100
    service.ingest_object(db, 'inbox/second.MOV')
    rows = db.query(Notification).filter_by(type='session_video', session_id=sid).all()
    assert {r.user_id for r in rows} == {users['alice'].id, users['bob'].id}
    assert len(rows) == len(pushes) == 2
    assert all(path == f'/sessions/shared/{sid}' for _, path in pushes)
    assert len(emails) == 1 and emails[0][0] == users['alice'].email
    assert f'/sessions/shared/{sid}' in emails[0][1]
    inbox = login('alice').get('/api/v1/notifications').json()['items']
    assert any(row.get('session_id') == sid for row in inbox)


def test_notification_batches_do_not_truncate_large_groups(sessions_env, monkeypatch):
    from app.models.user_auth import AppUser
    db, _, users, *_ = sessions_env
    monkeypatch.setattr(get_settings(), 'calendar_enabled', True)
    o = setup_group(db, users)
    assignment = db.query(TrainingGroupMembership).first()
    for i in range(105):
        user = AppUser(email=f'large-{i}@example.test', display_name=f'Membre {i}', session_email_enabled=False)
        db.add(user); db.flush()
        membership = ClubMembership(club_id=assignment.club_id, user_id=user.id, source='manager')
        db.add(membership); db.flush()
        db.add(TrainingGroupMembership(club_id=assignment.club_id, group_id=assignment.group_id,
            club_membership_id=membership.id, user_id=user.id, effective_from=date(2026, 1, 1)))
    db.commit()
    monkeypatch.setattr('app.services.push_service.fanout_for_rows', lambda *args: None)
    monkeypatch.setattr('app.services.email_service.is_email_configured', lambda: False)
    first = service.ingest_object(db, KEY)
    sid = first.session_id
    service.ingest_object(db, KEY)
    assert db.query(Notification).filter_by(session_id=sid).count() == 108
