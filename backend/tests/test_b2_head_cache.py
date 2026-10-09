"""The provider HEAD proof is reused briefly per object and credential; failures never are."""
import pytest

from app.config import get_settings
from app.services import b2_presign


class FakeClient:
    def __init__(self):
        self.calls = 0
        self.fail = False

    def head_object(self, Bucket, Key):
        self.calls += 1
        if self.fail:
            raise RuntimeError("403")


@pytest.fixture
def client(monkeypatch):
    fake = FakeClient()
    clock = {"now": 1000.0}
    monkeypatch.setattr(b2_presign, "_b2_client", lambda: fake)
    monkeypatch.setattr(b2_presign, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(b2_presign, "_presign_client_fingerprint", ("key-a",))
    monkeypatch.setattr(get_settings(), "media_playback_head_cache_seconds", 300)
    b2_presign._head_ok_cache.clear()
    fake.clock = clock
    yield fake
    b2_presign._head_ok_cache.clear()


def test_success_is_reused_until_it_expires(client):
    assert b2_presign.head_object(bucket="prod", object_key="a.mov")
    assert b2_presign.head_object(bucket="prod", object_key="a.mov")
    assert client.calls == 1
    b2_presign.head_object(bucket="prod", object_key="b.mov")  # another object is its own proof
    assert client.calls == 2
    client.clock["now"] += 301
    b2_presign.head_object(bucket="prod", object_key="a.mov")
    assert client.calls == 3


def test_failures_are_never_cached(client):
    client.fail = True
    for _ in range(2):
        with pytest.raises(b2_presign.PresignUnavailable):
            b2_presign.head_object(bucket="prod", object_key="a.mov")
    assert client.calls == 2


def test_a_rotated_credential_checks_again(client, monkeypatch):
    b2_presign.head_object(bucket="prod", object_key="a.mov")
    monkeypatch.setattr(b2_presign, "_presign_client_fingerprint", ("key-b",))
    client.fail = True
    with pytest.raises(b2_presign.PresignUnavailable):
        b2_presign.head_object(bucket="prod", object_key="a.mov")


def test_zero_disables_the_cache(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "media_playback_head_cache_seconds", 0)
    b2_presign.head_object(bucket="prod", object_key="a.mov")
    b2_presign.head_object(bucket="prod", object_key="a.mov")
    assert client.calls == 2
