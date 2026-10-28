# Participants synchro

`SYNC MAT` / `MAT SYNC` means the configured primary diver + MAT.
`SYNC MAT+SARA` means those two explicit profiles. `SYNC` alone keeps an
unknown partner. Names/aliases resolve by exact canonical identity; unrelated
annotations, duplicate participants and unresolved identities fail closed.
Existing member profiles sharing a display name are not silently merged.

`dive_sync_pairs` stores the effective pair separately from imported
`person_name` and `raw_caption`. A reviewed pair survives ALL machine replays,
including an unchanged caption after loss of Mac state and a caption that no
longer says SYNC. `dives.diver_id` remains the representative owner: primary
when present, otherwise the first participant. This change does not introduce
shared account management rights for the second participant. A later source
caption that contradicts/cannot resolve a reviewed pair sets `conflict`; it
never overwrites the pair. Source metadata continues to update.

## Rollout

1. Take a private DB backup and preserve the private review export/journal.
2. Apply `backend/migrations/add_dive_sync_pairs.sql` BEFORE backend deployment.
   Additive, no historical inference; leave table on rollback.
3. Merge through GitHub and deploy using `ci/ship.sh server --dry-run`, then
   `ci/ship.sh server`. Upgrade Mac via `ci/ship.sh mac --dry-run`, then `mac`.
4. From the deployed backend container, feed the private export to
   `python -m scripts.migrate_sync_review` (dry-run). Compare the report with
   117 decisions (115 include primary) and skip test row 1980. No stale rows
   may be applied. Dry-run rolls back all writes, including new profiles;
   PostgreSQL sequences may still advance.
5. Re-run with `--apply`. Whole transaction, row locks and advisory lock;
   reject stale/missing identities, inactive participants or different existing
   review. Create new CLARA/MYMY/BERE profiles only when canonical name/alias
   is unclaimed. A validated unknown participant remains NULL/incomplete.
6. Verify 117 reviewed rows, 115 with primary, two foreign pairs and one
   incomplete pair; re-run dry-run to confirm idempotence. Keep export,
   journal, backup and report private, outside git.

## Photos originals

Primary present -> keep. Incomplete/conflicting/unresolved -> keep. Two
identified other active divers -> eligible only with ALL original durable B2,
caption/version, agent identity and export checks intact. Old Mac workers
cannot authorize sync deletion. New workers pin the pair revision when a NEW
continuous ingest is enqueued; later identity changes invalidate the request.
No historical scan/review/migration enqueues deletion. Existing opt-in and
PhotoKit protections are unchanged. There is still a small distributed race
between the last server check and PhotoKit commit, as for existing metadata
checks; no claim of a cross-system atomic transaction is made.

Do not rewrite Photos captions or Mac sync_state.json for the migration.
