"""Exercise the public reserved-ingress API and drain its real worker in tests."""
from unittest.mock import patch
from sqlalchemy.orm import sessionmaker
from app.services import upload_queue


def publish_upload(db, client, *, data, files):
    filename, content, *_ = files['file']
    reserved = client.post('/api/v1/dives/uploads', json={**data, 'filename': filename})
    if reserved.status_code != 202:
        return reserved
    url = '/api/v1/dives/uploads/' + data['upload_id']
    if reserved.json()['status'] == 'receiving':
        received = client.put(url + '/content', content=content)
        if received.status_code != 202:
            return received
    with patch.object(upload_queue, 'engine', db.get_bind()), patch.object(upload_queue, 'SessionLocal', sessionmaker(bind=db.get_bind(), expire_on_commit=False)):
        upload_queue.process_one()
    result = client.get(url)
    if result.json()['status'] == 'ready':
        return client.get('/api/v1/dives/' + str(result.json()['dive_id']))
    return result
