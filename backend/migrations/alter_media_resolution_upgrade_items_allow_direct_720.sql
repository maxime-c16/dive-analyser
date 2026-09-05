BEGIN;

-- A direct 720p item has no prior 360p cache row to retire.
ALTER TABLE media_resolution_upgrade_items
    ALTER COLUMN old_cache_entry_id DROP NOT NULL;

COMMIT;
