-- Club calendar domain (Task02). Additive and idempotent: safe to re-run.
-- Apply MANUALLY after add_user_auth_tables.sql and before setting
-- CALENDAR_ENABLED=true. App startup never creates these tables (they are
-- tagged sql_migration_only in app/models/calendar.py). The backend works
-- unchanged with or without them while the flag is off.
-- Rollback: set CALENDAR_ENABLED=false; keep the tables for investigation.
-- No destructive down migration.
BEGIN;

CREATE TABLE IF NOT EXISTS clubs (
 id SERIAL PRIMARY KEY,
 slug VARCHAR(64) NOT NULL UNIQUE,
 name VARCHAR(160) NOT NULL,
 short_name VARCHAR(40),
 timezone VARCHAR(64) NOT NULL DEFAULT 'Europe/Paris',
 self_join_enabled BOOLEAN NOT NULL DEFAULT false,
 archived_at TIMESTAMP,
 created_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS club_memberships (
 id SERIAL PRIMARY KEY,
 club_id INTEGER NOT NULL REFERENCES clubs(id) ON DELETE RESTRICT,
 user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
 role VARCHAR(16) NOT NULL DEFAULT 'member',
 can_publish BOOLEAN NOT NULL DEFAULT false,
 can_assign_groups BOOLEAN NOT NULL DEFAULT false,
 status VARCHAR(16) NOT NULL DEFAULT 'active',
 source VARCHAR(16) NOT NULL,
 started_at TIMESTAMP NOT NULL DEFAULT now(),
 ended_at TIMESTAMP,
 created_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
 ended_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
 CONSTRAINT ck_club_membership_role CHECK (role IN ('member', 'coach', 'manager')),
 CONSTRAINT ck_club_membership_status CHECK (status IN ('active', 'left', 'removed')),
 CONSTRAINT ck_club_membership_source CHECK (source IN ('signup', 'admin_legacy', 'manager')),
 CONSTRAINT ck_club_membership_ended CHECK ((status = 'active') = (ended_at IS NULL)),
 CONSTRAINT uq_club_membership_id_club UNIQUE (id, club_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_club_membership_active ON club_memberships (club_id, user_id) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_club_memberships_user ON club_memberships (user_id, club_id);

CREATE TABLE IF NOT EXISTS training_groups (
 id SERIAL PRIMARY KEY,
 club_id INTEGER NOT NULL REFERENCES clubs(id) ON DELETE RESTRICT,
 slug VARCHAR(64) NOT NULL,
 name VARCHAR(120) NOT NULL,
 archived_at TIMESTAMP,
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 CONSTRAINT uq_training_group_slug UNIQUE (club_id, slug),
 CONSTRAINT uq_training_group_id_club UNIQUE (id, club_id)
);

CREATE TABLE IF NOT EXISTS training_group_memberships (
 id SERIAL PRIMARY KEY,
 club_id INTEGER NOT NULL,
 group_id INTEGER NOT NULL,
 club_membership_id INTEGER NOT NULL,
 user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
 effective_from DATE NOT NULL,
 effective_to DATE,
 assigned_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
 ended_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 CONSTRAINT fk_group_membership_group_club FOREIGN KEY (group_id, club_id)
   REFERENCES training_groups (id, club_id) ON DELETE RESTRICT,
 CONSTRAINT fk_group_membership_club_membership FOREIGN KEY (club_membership_id, club_id)
   REFERENCES club_memberships (id, club_id) ON DELETE CASCADE,
 CONSTRAINT ck_group_membership_dates CHECK (effective_to IS NULL OR effective_to > effective_from)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_group_membership_open ON training_group_memberships (club_id, user_id) WHERE effective_to IS NULL;
CREATE INDEX IF NOT EXISTS ix_group_memberships_group ON training_group_memberships (group_id, effective_from);
CREATE INDEX IF NOT EXISTS ix_group_memberships_user ON training_group_memberships (user_id, club_id, effective_from);

CREATE TABLE IF NOT EXISTS calendars (
 id SERIAL PRIMARY KEY,
 kind VARCHAR(16) NOT NULL,
 club_id INTEGER REFERENCES clubs(id) ON DELETE RESTRICT,
 training_group_id INTEGER,
 owner_user_id INTEGER REFERENCES app_users(id) ON DELETE CASCADE,
 name VARCHAR(160) NOT NULL,
 archived_at TIMESTAMP,
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 CONSTRAINT fk_calendar_group_club FOREIGN KEY (training_group_id, club_id)
   REFERENCES training_groups (id, club_id) ON DELETE RESTRICT,
 CONSTRAINT ck_calendar_kind CHECK (kind IN ('club', 'group', 'personal', 'federal')),
 CONSTRAINT ck_calendar_owner CHECK (
   (kind = 'club' AND club_id IS NOT NULL AND training_group_id IS NULL AND owner_user_id IS NULL)
   OR (kind = 'group' AND club_id IS NOT NULL AND training_group_id IS NOT NULL AND owner_user_id IS NULL)
   OR (kind = 'personal' AND owner_user_id IS NOT NULL AND club_id IS NULL AND training_group_id IS NULL)
   OR (kind = 'federal' AND club_id IS NULL AND training_group_id IS NULL AND owner_user_id IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_calendar_club ON calendars (club_id) WHERE kind = 'club';
CREATE UNIQUE INDEX IF NOT EXISTS uq_calendar_group ON calendars (training_group_id) WHERE kind = 'group';

CREATE TABLE IF NOT EXISTS calendar_subscriptions (
 calendar_id INTEGER NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 PRIMARY KEY (calendar_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_calendar_subscriptions_user ON calendar_subscriptions (user_id);

CREATE TABLE IF NOT EXISTS calendar_events (
 id SERIAL PRIMARY KEY,
 calendar_id INTEGER NOT NULL REFERENCES calendars(id) ON DELETE RESTRICT,
 organizer_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
 created_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
 event_type VARCHAR(16) NOT NULL,
 audience VARCHAR(16) NOT NULL,
 status VARCHAR(16) NOT NULL DEFAULT 'draft',
 title VARCHAR(200) NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 venue_name VARCHAR(200),
 venue_address VARCHAR(300),
 map_url VARCHAR(500),
 timezone VARCHAR(64) NOT NULL,
 recurrence_rule VARCHAR(500),
 scoring_competition_id INTEGER,
 version INTEGER NOT NULL DEFAULT 1,
 published_at TIMESTAMP,
 cancelled_at TIMESTAMP,
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 updated_at TIMESTAMP NOT NULL DEFAULT now(),
 CONSTRAINT ck_calendar_event_type CHECK (event_type IN ('training', 'camp', 'outing', 'competition', 'other')),
 CONSTRAINT ck_calendar_event_audience CHECK (audience IN ('group', 'club', 'community', 'invited')),
 CONSTRAINT ck_calendar_event_status CHECK (status IN ('draft', 'published', 'cancelled')),
 CONSTRAINT ck_calendar_event_cancelled CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL)),
 CONSTRAINT ck_calendar_event_version CHECK (version >= 1)
);
CREATE INDEX IF NOT EXISTS ix_calendar_events_calendar ON calendar_events (calendar_id, status);
CREATE INDEX IF NOT EXISTS ix_calendar_events_organizer ON calendar_events (organizer_user_id);

CREATE TABLE IF NOT EXISTS event_occurrences (
 id SERIAL PRIMARY KEY,
 event_id INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
 occurrence_key VARCHAR(120) NOT NULL,
 is_all_day BOOLEAN NOT NULL DEFAULT false,
 starts_at TIMESTAMP,
 ends_at TIMESTAMP,
 start_date DATE,
 end_date DATE,
 window_start TIMESTAMP NOT NULL,
 window_end TIMESTAMP NOT NULL,
 status VARCHAR(16) NOT NULL DEFAULT 'scheduled',
 venue_name VARCHAR(200),
 filmed_session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
 version INTEGER NOT NULL DEFAULT 1,
 cancelled_at TIMESTAMP,
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 updated_at TIMESTAMP NOT NULL DEFAULT now(),
 CONSTRAINT uq_occurrence_key UNIQUE (event_id, occurrence_key),
 CONSTRAINT ck_occurrence_status CHECK (status IN ('scheduled', 'cancelled')),
 CONSTRAINT ck_occurrence_cancelled CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL)),
 CONSTRAINT ck_occurrence_time_form CHECK (
   (is_all_day AND start_date IS NOT NULL AND end_date > start_date AND starts_at IS NULL AND ends_at IS NULL)
   OR (NOT is_all_day AND starts_at IS NOT NULL AND ends_at > starts_at AND start_date IS NULL AND end_date IS NULL)),
 CONSTRAINT ck_occurrence_window CHECK (window_end > window_start)
);
CREATE INDEX IF NOT EXISTS ix_occurrences_window ON event_occurrences (window_start, id);
CREATE INDEX IF NOT EXISTS ix_occurrences_event ON event_occurrences (event_id, window_start);

CREATE TABLE IF NOT EXISTS event_invitations (
 id SERIAL PRIMARY KEY,
 event_id INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
 invitee_user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
 invited_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
 status VARCHAR(16) NOT NULL DEFAULT 'pending',
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 responded_at TIMESTAMP,
 revoked_at TIMESTAMP,
 CONSTRAINT uq_event_invitation UNIQUE (event_id, invitee_user_id),
 CONSTRAINT ck_event_invitation_status CHECK (status IN ('pending', 'accepted', 'declined', 'revoked')),
 CONSTRAINT ck_event_invitation_revoked CHECK ((status = 'revoked') = (revoked_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ix_event_invitations_invitee ON event_invitations (invitee_user_id, status);

CREATE TABLE IF NOT EXISTS occurrence_interests (
 occurrence_id INTEGER NOT NULL REFERENCES event_occurrences(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
 state VARCHAR(16) NOT NULL,
 updated_at TIMESTAMP NOT NULL DEFAULT now(),
 PRIMARY KEY (occurrence_id, user_id),
 CONSTRAINT ck_occurrence_interest_state CHECK (state IN ('interested', 'maybe', 'declined'))
);

CREATE TABLE IF NOT EXISTS occurrence_absence_reports (
 occurrence_id INTEGER NOT NULL REFERENCES event_occurrences(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
 reported_at TIMESTAMP NOT NULL DEFAULT now(),
 withdrawn_at TIMESTAMP,
 PRIMARY KEY (occurrence_id, user_id)
);

CREATE TABLE IF NOT EXISTS calendar_sources (
 id SERIAL PRIMARY KEY,
 kind VARCHAR(24) NOT NULL,
 label VARCHAR(200) NOT NULL,
 url VARCHAR(1000),
 club_id INTEGER REFERENCES clubs(id) ON DELETE RESTRICT,
 parent_source_id INTEGER REFERENCES calendar_sources(id) ON DELETE SET NULL,
 is_private BOOLEAN NOT NULL DEFAULT true,
 artifact_sha256 VARCHAR(64),
 storage_ref VARCHAR(500),
 last_checked_at TIMESTAMP,
 last_success_at TIMESTAMP,
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 CONSTRAINT ck_calendar_source_kind CHECK (kind IN ('workbook', 'pdf_schedule', 'organizer_page', 'federation_page', 'manual'))
);
CREATE INDEX IF NOT EXISTS ix_calendar_sources_parent ON calendar_sources (parent_source_id);

CREATE TABLE IF NOT EXISTS calendar_import_runs (
 id SERIAL PRIMARY KEY,
 source_id INTEGER NOT NULL REFERENCES calendar_sources(id) ON DELETE RESTRICT,
 source_sha256 VARCHAR(64) NOT NULL,
 parser_version VARCHAR(40) NOT NULL,
 status VARCHAR(16) NOT NULL,
 summary JSON NOT NULL DEFAULT '{}',
 created_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 applied_at TIMESTAMP,
 CONSTRAINT ck_calendar_import_status CHECK (status IN ('previewed', 'applied', 'failed'))
);
CREATE INDEX IF NOT EXISTS ix_calendar_import_runs_source ON calendar_import_runs (source_id, created_at);

CREATE TABLE IF NOT EXISTS event_resources (
 id SERIAL PRIMARY KEY,
 event_id INTEGER REFERENCES calendar_events(id) ON DELETE CASCADE,
 club_id INTEGER REFERENCES clubs(id) ON DELETE RESTRICT,
 kind VARCHAR(24) NOT NULL,
 label VARCHAR(200) NOT NULL,
 url VARCHAR(1000),
 restricted_to_club BOOLEAN NOT NULL DEFAULT false,
 deadline_kind VARCHAR(24),
 due_at TIMESTAMP,
 edition_label VARCHAR(80),
 source_verified_at TIMESTAMP,
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 CONSTRAINT ck_event_resource_kind CHECK (kind IN ('official_info', 'registration', 'dive_sheets', 'results', 'club_chat', 'rules', 'other')),
 CONSTRAINT ck_event_resource_deadline CHECK (deadline_kind IS NULL OR deadline_kind IN ('club_cutoff', 'official_entry', 'dive_sheet')),
 CONSTRAINT ck_event_resource_owner CHECK ((event_id IS NULL) <> (club_id IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_event_resources_event ON event_resources (event_id);
CREATE INDEX IF NOT EXISTS ix_event_resources_club ON event_resources (club_id);

CREATE TABLE IF NOT EXISTS calendar_source_mappings (
 id SERIAL PRIMARY KEY,
 source_id INTEGER NOT NULL REFERENCES calendar_sources(id) ON DELETE RESTRICT,
 external_key VARCHAR(200) NOT NULL,
 target_type VARCHAR(16) NOT NULL,
 event_id INTEGER REFERENCES calendar_events(id) ON DELETE SET NULL,
 occurrence_id INTEGER REFERENCES event_occurrences(id) ON DELETE SET NULL,
 resource_id INTEGER REFERENCES event_resources(id) ON DELETE SET NULL,
 last_import_run_id INTEGER REFERENCES calendar_import_runs(id) ON DELETE SET NULL,
 locally_overridden BOOLEAN NOT NULL DEFAULT false,
 provenance JSON NOT NULL DEFAULT '{}',
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 updated_at TIMESTAMP NOT NULL DEFAULT now(),
 CONSTRAINT uq_calendar_source_mapping UNIQUE (source_id, target_type, external_key),
 CONSTRAINT ck_calendar_mapping_target CHECK (target_type IN ('event', 'occurrence', 'resource'))
);
CREATE INDEX IF NOT EXISTS ix_calendar_mappings_event ON calendar_source_mappings (event_id);
CREATE INDEX IF NOT EXISTS ix_calendar_mappings_occurrence ON calendar_source_mappings (occurrence_id);

CREATE TABLE IF NOT EXISTS calendar_change_log (
 id SERIAL PRIMARY KEY,
 event_id INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
 occurrence_id INTEGER REFERENCES event_occurrences(id) ON DELETE SET NULL,
 event_version INTEGER NOT NULL,
 change_kind VARCHAR(16) NOT NULL,
 actor_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
 import_run_id INTEGER REFERENCES calendar_import_runs(id) ON DELETE SET NULL,
 changes JSON NOT NULL DEFAULT '{}',
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 CONSTRAINT ck_calendar_change_kind CHECK (change_kind IN ('created', 'published', 'updated', 'time_changed', 'venue_changed', 'cancelled', 'imported'))
);
CREATE INDEX IF NOT EXISTS ix_calendar_change_log_event ON calendar_change_log (event_id, id);

COMMIT;
