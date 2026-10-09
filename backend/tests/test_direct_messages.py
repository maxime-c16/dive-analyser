from uuid import uuid4
from tests.test_member_dive_visibility import workspace
from app.models.direct_message import Conversation, DirectMessage, MessageReceipt, ConversationParticipant
from app.models.notification import Notification


def start(login, users):
    response = login('alice').post('/api/v1/messages/conversations', json={'user_id': users['bob'].id})
    assert response.status_code == 200, response.text
    return response.json()['id']


def send(client, cid, **data):
    return client.post(f'/api/v1/messages/conversations/{cid}/messages', json={'client_id': str(uuid4()), **data})


def test_membership_idempotency_text_and_private_notifications(workspace):
    db, login, dives, users, _ = workspace
    cid = start(login, users)
    assert login('bob').post('/api/v1/messages/conversations', json={'user_id': users['alice'].id}).json()['id'] == cid
    url = f'/api/v1/messages/conversations/{cid}'
    client = login('alice')
    key = str(uuid4())
    payload = dict(client_id=key, body='Private conversation @bob', mentions=[dict(user_id=users['bob'].id, start=21, end=25)])
    response = client.post(url + '/messages', json=payload)
    assert response.status_code == 201, response.text
    row = response.json()
    assert client.post(url + '/messages', json=payload).json()['id'] == row['id']
    assert db.query(DirectMessage).count() == 1
    note = db.query(Notification).filter_by(type='direct_message').one()
    assert note.user_id == users['bob'].id and note.conversation_id == cid
    assert 'Private conversation' not in note.body
    for suffix in ('', '/messages'):
        assert login('viewer').get(url + suffix).status_code == 404
    assert login('viewer').get('/api/v1/messages/conversations').json()['items'] == []
    assert send(login('viewer'), cid, body='Intrusion').status_code == 404
    assert login('viewer').put(url + f"/messages/{row['id']}/reaction", json={'reacted': True}).status_code == 404
    assert login('viewer').post(url + '/receipts', json={'message_ids': [row['id']], 'read': True}).status_code == 404
    assert login('alice').post(url + '/messages', json={'client_id': str(uuid4()), 'body': ''}).status_code == 422
    assert login('alice').post('/api/v1/messages/conversations', json={'user_id': users['alice'].id}).status_code == 422
    client.cookies.clear()
    assert client.get(url + '/messages').status_code == 401


def test_honest_monotonic_receipts_and_reactions(workspace):
    db, login, _, users, _ = workspace
    cid = start(login, users)
    url = f'/api/v1/messages/conversations/{cid}'
    message = send(login('alice'), cid, body='Hello').json()
    assert message['receipts'][0]['delivered_at'] is None
    assert login('bob').get(url + '/messages').status_code == 200
    receipt = db.query(MessageReceipt).one()
    assert receipt.delivered_at is None and receipt.read_at is None
    client = login('bob')
    assert client.post(url + '/receipts', json={'message_ids': [message['id']], 'read': False}).status_code == 204
    delivered = login('alice').get(url + '/messages').json()['items'][0]['receipts'][0]
    assert delivered['delivered_at'] and delivered['read_at'] is None
    assert login('alice').post(url + '/receipts', json={'message_ids': [message['id']], 'read': True}).status_code == 404
    for _ in range(2):
        assert login('bob').post(url + '/receipts', json={'message_ids': [message['id']], 'read': True}).status_code == 204
    read = login('alice').get(url + '/messages').json()['items'][0]['receipts'][0]
    assert read['delivered_at'] == delivered['delivered_at'] and read['read_at'] >= read['delivered_at']
    assert login('bob').get('/api/v1/messages/conversations').json()['items'][0]['unread_count'] == 0
    for _ in range(2):
        reaction = login('bob').put(url + f"/messages/{message['id']}/reaction", json={'reacted': True})
        assert reaction.json()['reactions'] == [dict(user_id=users['bob'].id, emoji='❤️')]
    assert login('bob').put(url + f"/messages/{message['id']}/reaction", json={'reacted': False}).json()['reactions'] == []


def test_dive_cards_do_not_grant_access_and_redact_after_revocation(workspace):
    db, login, dives, users, _ = workspace
    cid = start(login, users)
    url = f'/api/v1/messages/conversations/{cid}'
    assert send(login('alice'), cid, dive_id=dives['alice-private']).status_code == 404
    message = send(login('alice'), cid, dive_id=dives['alice-public']).json()
    assert message['dive']['available'] is True
    assert login('bob').get(url + '/messages').json()['items'][0]['dive']['id'] == dives['alice-public']
    assert login('alice').put(f"/api/v1/dives/{dives['alice-public']}", json={'visibility': 'private'}).status_code == 200
    assert login('bob').get(url + '/messages').json()['items'][0]['dive'] == dict(available=False)
    assert login('bob').get('/api/v1/messages/conversations').json()['items'][0]['latest']['dive'] == dict(available=False)
    assert login('alice').get(url + '/messages').json()['items'][0]['dive']['available'] is True
    # Text and receipts remain visible to members after a card loses access.
    assert send(login('bob'), cid, body='Still here').status_code == 201


def test_message_pagination_and_origin_guard(workspace):
    db, login, _, users, _ = workspace
    cid = start(login, users)
    client = login('alice')
    url = f'/api/v1/messages/conversations/{cid}'
    assert client.post(url + '/messages', headers={'Origin': 'https://evil.test'}, json={'client_id': str(uuid4()), 'body': 'CSRF'}).status_code == 403
    db.add_all([DirectMessage(conversation_id=cid, sender_id=users['alice'].id, client_id=str(uuid4()), body=str(i)) for i in range(55)])
    db.commit()
    first = client.get(url + '/messages').json()
    second = client.get(url + f"/messages?before={first['next_before']}").json()
    assert len(first['items']) == 50 and len(second['items']) == 5
    assert len({m['id'] for m in first['items'] + second['items']}) == 55
    assert first['items'][0]['id'] < first['items'][-1]['id']
    assert second['next_before'] is None


def test_unread_count_aggregates_beyond_inbox_pages(workspace):
    db, login, _, users, _ = workspace
    alice, bob = users['alice'], users['bob']
    conversations = [Conversation(kind='direct', direct_key=f'{alice.id}:{bob.id}:{i}') for i in range(251)]
    db.add_all(conversations)
    db.commit()
    db.add_all([ConversationParticipant(conversation_id=c.id, user_id=u.id) for c in conversations for u in (alice, bob)])
    db.commit()
    db.add_all([DirectMessage(conversation_id=c.id, sender_id=bob.id, client_id=str(uuid4()), body='ping') for c in conversations])
    db.commit()
    ids = [c.id for c in conversations]
    db.add_all([MessageReceipt(message_id=m.id, user_id=alice.id) for m in db.query(DirectMessage).filter(DirectMessage.conversation_id.in_(ids))])
    db.commit()
    client = login('alice')
    # Even the largest inbox page (50) cannot reach row 251 in five pages.
    assert len(client.get('/api/v1/messages/conversations?limit=50').json()['items']) == 50
    assert client.get('/api/v1/messages/unread-count').json()['unread_count'] == 251
    assert login('bob').get('/api/v1/messages/unread-count').json()['unread_count'] == 0
    # login() swaps the shared client cookie, so sign back in as alice.
    client = login('alice')
    cid = client.get('/api/v1/messages/conversations').json()['items'][0]['id']
    visible = [m['id'] for m in client.get(f'/api/v1/messages/conversations/{cid}/messages').json()['items']]
    # Reading one conversation decrements the aggregate.
    assert client.post(f'/api/v1/messages/conversations/{cid}/receipts', json={'message_ids': visible, 'read': True}).status_code == 204
    assert client.get('/api/v1/messages/unread-count').json()['unread_count'] == 250
