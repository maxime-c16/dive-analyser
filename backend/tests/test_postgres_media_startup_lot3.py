from tests.test_postgres_media_startup_lot1 import pg  # noqa: F401
from tests.test_media_startup_lot3 import root, test_real_ffmpeg_bounded_webp_and_backfill as exercise  # noqa: F401


def test_animated_roundtrip_postgres(pg, root, monkeypatch):
    _, factory, _ = pg
    with factory() as db:
        exercise(db, root, monkeypatch)
