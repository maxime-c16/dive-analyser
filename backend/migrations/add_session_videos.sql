-- Shared sessions (docs/features/SHARED_SESSIONS.md). Apply BEFORE deploying the
-- backend that ships the feature. Additive and re-runnable; the previous backend
-- ignores these tables. Requires add_dive_sharing.sql (dive_guests).
BEGIN;
CREATE TABLE IF NOT EXISTS session_videos (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    owner_user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    bucket VARCHAR(63) NOT NULL,
    object_key VARCHAR(1024) NOT NULL,
    size_bytes BIGINT,
    etag VARCHAR(80),
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    claimed_at TIMESTAMP,
    last_error VARCHAR(200),
    recorded_at TIMESTAMP,
    recorded_date DATE,
    duration_seconds DOUBLE PRECISION,
    video_codec VARCHAR(32),
    video_profile VARCHAR(32),
    codec_string VARCHAR(64),
    audio_codec_string VARCHAR(32),
    pix_fmt VARCHAR(32),
    color_transfer VARCHAR(32),
    width INTEGER,
    height INTEGER,
    fps DOUBLE PRECISION,
    bit_rate BIGINT,
    notified_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_session_videos_object UNIQUE (bucket, object_key),
    CONSTRAINT ck_session_videos_status CHECK (status IN ('pending', 'probing', 'ready', 'failed'))
);
CREATE INDEX IF NOT EXISTS ix_session_videos_session_id ON session_videos(session_id);
CREATE INDEX IF NOT EXISTS ix_session_videos_recorded ON session_videos(recorded_at);
CREATE TABLE IF NOT EXISTS session_video_shares (
    id SERIAL PRIMARY KEY,
    session_video_id INTEGER NOT NULL REFERENCES session_videos(id) ON DELETE CASCADE,
    created_by INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_session_video_shares_session_video_id ON session_video_shares(session_video_id);
CREATE TABLE IF NOT EXISTS session_video_guest_access (
    share_id INTEGER NOT NULL REFERENCES session_video_shares(id) ON DELETE CASCADE,
    guest_id INTEGER NOT NULL REFERENCES dive_guests(id) ON DELETE CASCADE,
    PRIMARY KEY (share_id, guest_id)
);
CREATE TABLE IF NOT EXISTS session_video_playback_issues (
    id SERIAL PRIMARY KEY,
    session_video_id INTEGER NOT NULL REFERENCES session_videos(id) ON DELETE CASCADE,
    reason VARCHAR(16) NOT NULL,
    viewer_user_id INTEGER REFERENCES app_users(id) ON DELETE CASCADE,
    viewer_guest_id INTEGER REFERENCES dive_guests(id) ON DELETE CASCADE,
    user_agent VARCHAR(200),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_session_video_issues_video_created ON session_video_playback_issues(session_video_id, created_at);
COMMIT;
-- Rollback (destroys session video rows and their share links; B2 objects stay):
-- DROP TABLE session_video_playback_issues, session_video_guest_access, session_video_shares, session_videos;
