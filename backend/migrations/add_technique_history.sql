-- Additive migration. Run before application rollout. Retain on rollback.
BEGIN;
ALTER TABLE dives ADD COLUMN IF NOT EXISTS history_occurred_at timestamp;
UPDATE dives SET history_occurred_at=dive_datetime WHERE history_occurred_at IS NULL;
ALTER TABLE dives ALTER COLUMN history_occurred_at SET NOT NULL;
CREATE INDEX IF NOT EXISTS ix_dives_history_context ON dives(diver_id,dive_code,platform_type,height,history_occurred_at,id);
CREATE OR REPLACE FUNCTION preserve_dive_history_order() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='INSERT' THEN NEW.history_occurred_at=coalesce(NEW.history_occurred_at,NEW.dive_datetime);
 ELSIF NEW.history_occurred_at IS DISTINCT FROM OLD.history_occurred_at AND coalesce(current_setting('app.history_correction',true),'off') <> 'on' THEN
 RAISE EXCEPTION 'Immutable history occurrence';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS dive_history_order ON dives;
CREATE TRIGGER dive_history_order BEFORE INSERT OR UPDATE ON dives FOR EACH ROW EXECUTE FUNCTION preserve_dive_history_order();

CREATE TABLE IF NOT EXISTS technique_tracks (
	id SERIAL NOT NULL, 
	diver_id INTEGER NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	revision INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (diver_id, name), 
	FOREIGN KEY(diver_id) REFERENCES divers (id)
)

;

CREATE TABLE IF NOT EXISTS techniques (
	id SERIAL NOT NULL, 
	track_id INTEGER NOT NULL, 
	label VARCHAR(120) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(track_id) REFERENCES technique_tracks (id)
)

;

CREATE TABLE IF NOT EXISTS technique_episodes (
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	id SERIAL NOT NULL, 
	track_id INTEGER NOT NULL, 
	technique_id INTEGER, 
	scope VARCHAR(10) NOT NULL, 
	apparatus VARCHAR(20) NOT NULL, 
	height VARCHAR(5) NOT NULL, 
	position VARCHAR(1), 
	sync BOOLEAN, 
	start_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	start_id INTEGER NOT NULL, 
	end_at TIMESTAMP WITHOUT TIME ZONE, 
	end_id INTEGER, 
	uncertain_until TIMESTAMP WITHOUT TIME ZONE, 
	anchor_id INTEGER, 
	precision VARCHAR(20) NOT NULL, 
	timezone VARCHAR(80) NOT NULL, 
	gap BOOLEAN NOT NULL, 
	source_episode_id INTEGER, 
	notes VARCHAR(2000) NOT NULL, 
	deleted BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_technique_episode_state CHECK ((gap AND technique_id IS NULL) OR (NOT gap AND technique_id IS NOT NULL)), 
	CONSTRAINT ck_technique_episode_end CHECK ((end_at IS NULL AND end_id IS NULL) OR (end_at IS NOT NULL AND end_id IS NOT NULL)), 
	FOREIGN KEY(track_id) REFERENCES technique_tracks (id), 
	FOREIGN KEY(technique_id) REFERENCES techniques (id), 
	FOREIGN KEY(anchor_id) REFERENCES dives (id) ON DELETE SET NULL, 
	FOREIGN KEY(source_episode_id) REFERENCES technique_episodes (id)
)

;
CREATE INDEX IF NOT EXISTS ix_technique_episode_lookup ON technique_episodes (track_id, apparatus, height, scope, start_at, start_id);

CREATE TABLE IF NOT EXISTS technique_assignments (
	id SERIAL NOT NULL, 
	track_id INTEGER NOT NULL, 
	dive_id INTEGER NOT NULL, 
	diver_id INTEGER NOT NULL, 
	code VARCHAR(10) NOT NULL, 
	apparatus VARCHAR(20) NOT NULL, 
	height VARCHAR(5) NOT NULL, 
	position VARCHAR(1), 
	sync BOOLEAN NOT NULL, 
	state VARCHAR(12) NOT NULL, 
	technique_id INTEGER, 
	episode_id INTEGER, 
	PRIMARY KEY (id), 
	UNIQUE (track_id, dive_id), 
	CONSTRAINT ck_technique_assignment_state CHECK ((state = 'technique' AND technique_id IS NOT NULL) OR (state IN ('mixed', 'unknown') AND technique_id IS NULL)), 
	FOREIGN KEY(track_id) REFERENCES technique_tracks (id), 
	FOREIGN KEY(dive_id) REFERENCES dives (id) ON DELETE CASCADE, 
	FOREIGN KEY(diver_id) REFERENCES divers (id), 
	FOREIGN KEY(technique_id) REFERENCES techniques (id), 
	FOREIGN KEY(episode_id) REFERENCES technique_episodes (id)
)

;

CREATE TABLE IF NOT EXISTS technique_revisions (
	id SERIAL NOT NULL, 
	track_id INTEGER NOT NULL, 
	revision INTEGER NOT NULL, 
	author_id INTEGER NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	operation VARCHAR(30) NOT NULL, 
	before JSON NOT NULL, 
	after JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (track_id, revision), 
	FOREIGN KEY(track_id) REFERENCES technique_tracks (id), 
	FOREIGN KEY(author_id) REFERENCES app_users (id)
)

;

CREATE TABLE IF NOT EXISTS technique_session_states (
	id SERIAL NOT NULL, 
	track_id INTEGER NOT NULL, 
	session_id INTEGER NOT NULL, 
	code VARCHAR(10) NOT NULL, 
	apparatus VARCHAR(20) NOT NULL, 
	height VARCHAR(5) NOT NULL, 
	position VARCHAR(1) NOT NULL, 
	sync BOOLEAN NOT NULL, 
	state VARCHAR(12) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (track_id, session_id, code, apparatus, height, position, sync), 
	CONSTRAINT ck_technique_session_state CHECK (state IN ('mixed', 'unknown')), 
	FOREIGN KEY(track_id) REFERENCES technique_tracks (id), 
	FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE CASCADE
)

;

CREATE TABLE IF NOT EXISTS technique_preferences (
 user_id integer PRIMARY KEY REFERENCES app_users(id),
 timezone varchar(80) NOT NULL
);

COMMIT;
