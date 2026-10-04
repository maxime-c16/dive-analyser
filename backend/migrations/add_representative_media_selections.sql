-- Auditable active selections for representative media cards.
-- Additive and safe to run after media population tables exist.

CREATE TABLE IF NOT EXISTS representative_media_selections (
    id SERIAL PRIMARY KEY,
    dive_code VARCHAR(10) NOT NULL,
    selection_role VARCHAR(20) NOT NULL,
    dive_id INTEGER NOT NULL REFERENCES dives(id) ON DELETE CASCADE,
    selection_version INTEGER NOT NULL DEFAULT 1,
    selection_reason VARCHAR(40) NOT NULL DEFAULT 'initial_manifest',
    replaced_selection_id INTEGER NULL REFERENCES representative_media_selections(id),
    active BOOLEAN NOT NULL DEFAULT true,
    created_by VARCHAR(80) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_representative_media_selections_dive_code
    ON representative_media_selections (dive_code);
CREATE INDEX IF NOT EXISTS ix_representative_media_selections_selection_role
    ON representative_media_selections (selection_role);
CREATE INDEX IF NOT EXISTS ix_representative_media_selections_dive_id
    ON representative_media_selections (dive_id);
CREATE INDEX IF NOT EXISTS ix_representative_media_selections_selection_reason
    ON representative_media_selections (selection_reason);
CREATE INDEX IF NOT EXISTS ix_representative_media_selections_active
    ON representative_media_selections (active);
CREATE INDEX IF NOT EXISTS ix_representative_selection_code_role_active
    ON representative_media_selections (dive_code, selection_role, active);

