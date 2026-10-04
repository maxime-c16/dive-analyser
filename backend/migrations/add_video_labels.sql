-- Store non-dive labels from Photos captions without polluting dive analytics.

CREATE TABLE IF NOT EXISTS video_labels (
    id SERIAL PRIMARY KEY,
    video_uuid VARCHAR(100) NOT NULL,
    label_type VARCHAR(50) NOT NULL,
    label_value VARCHAR(100) NOT NULL,
    source VARCHAR(50) NOT NULL DEFAULT 'photos_caption',
    raw_caption TEXT,
    video_filename VARCHAR(255),
    label_datetime TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_video_labels_uuid_type_source UNIQUE (video_uuid, label_type, source)
);

CREATE INDEX IF NOT EXISTS idx_video_labels_uuid ON video_labels(video_uuid);
CREATE INDEX IF NOT EXISTS idx_video_labels_type ON video_labels(label_type);
CREATE INDEX IF NOT EXISTS idx_video_labels_value ON video_labels(label_value);
CREATE INDEX IF NOT EXISTS idx_video_labels_source ON video_labels(source);
CREATE INDEX IF NOT EXISTS idx_video_labels_datetime ON video_labels(label_datetime);
CREATE INDEX IF NOT EXISTS idx_video_labels_type_value ON video_labels(label_type, label_value);
