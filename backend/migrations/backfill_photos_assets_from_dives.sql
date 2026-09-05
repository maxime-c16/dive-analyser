-- Backfill Photos asset rows for existing dives.
--
-- Safe/idempotent:
-- - Inserts one photos_assets row per distinct non-null dives.video_uuid.
-- - Uses ON CONFLICT to avoid duplicate assets on repeated runs.
-- - Only fills dives.photos_asset_id where it is currently NULL.
-- - Does not delete or destructively overwrite dive data.

INSERT INTO photos_assets (
    video_uuid,
    filename,
    raw_caption,
    created_at,
    updated_at,
    last_seen_on_mac_at
)
SELECT DISTINCT ON (d.video_uuid)
    d.video_uuid,
    d.video_filename,
    d.raw_caption,
    now(),
    now(),
    now()
FROM dives d
WHERE d.video_uuid IS NOT NULL
ORDER BY d.video_uuid, d.updated_at DESC NULLS LAST, d.id DESC
ON CONFLICT (video_uuid) DO UPDATE
SET
    filename = COALESCE(EXCLUDED.filename, photos_assets.filename),
    raw_caption = COALESCE(EXCLUDED.raw_caption, photos_assets.raw_caption),
    updated_at = now();

UPDATE dives d
SET photos_asset_id = pa.id
FROM photos_assets pa
WHERE d.video_uuid = pa.video_uuid
  AND d.photos_asset_id IS NULL;
