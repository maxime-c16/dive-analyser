-- Optional group names. Backend startup (create_all) creates this table on its
-- own, so applying this file by hand is optional; it is idempotent.
CREATE TABLE IF NOT EXISTS conversation_titles (
 conversation_id INTEGER PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
 title VARCHAR(60) NOT NULL,
 updated_by INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
 updated_at TIMESTAMP NOT NULL DEFAULT now()
);
