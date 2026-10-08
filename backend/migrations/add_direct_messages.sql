-- Apply after the profiles and mentions migrations, before backend deployment.
CREATE TABLE IF NOT EXISTS conversations (
 id SERIAL PRIMARY KEY, kind VARCHAR(16) NOT NULL DEFAULT 'direct',
 direct_key VARCHAR(64) UNIQUE, created_at TIMESTAMP NOT NULL DEFAULT now(),
 updated_at TIMESTAMP NOT NULL DEFAULT now(),
 CONSTRAINT ck_conversation_kind CHECK (kind IN ('direct', 'group'))
);
CREATE TABLE IF NOT EXISTS conversation_participants (
 conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
 joined_at TIMESTAMP NOT NULL DEFAULT now(), left_at TIMESTAMP,
 PRIMARY KEY (conversation_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_conversation_participants_user ON conversation_participants(user_id, conversation_id);
CREATE TABLE IF NOT EXISTS direct_messages (
 id SERIAL PRIMARY KEY, conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 sender_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL, client_id VARCHAR(36) NOT NULL,
 body VARCHAR(2000) NOT NULL DEFAULT '', mentions JSON NOT NULL DEFAULT '[]',
 dive_id INTEGER REFERENCES dives(id) ON DELETE SET NULL, has_dive INTEGER NOT NULL DEFAULT 0,
 created_at TIMESTAMP NOT NULL DEFAULT now(), CONSTRAINT uq_message_retry UNIQUE(sender_id, client_id)
);
CREATE INDEX IF NOT EXISTS ix_messages_conversation_id ON direct_messages(conversation_id, id);
CREATE TABLE IF NOT EXISTS message_receipts (
 message_id INTEGER NOT NULL REFERENCES direct_messages(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
 delivered_at TIMESTAMP, read_at TIMESTAMP, PRIMARY KEY(message_id, user_id)
);
CREATE TABLE IF NOT EXISTS message_reactions (
 message_id INTEGER NOT NULL REFERENCES direct_messages(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
 emoji VARCHAR(16) NOT NULL DEFAULT '❤️', PRIMARY KEY(message_id, user_id)
);
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE;
