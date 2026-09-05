# Mac Media Node Rollback

1. Disable new-agent leasing in `media_agents`.
2. Set `media.enabled: false` and `sync.enabled: false` in the new Mac config.
3. Restart or boot out `com.diveanalyzer.agent`.
4. Wait for any lease to finish or expire; do not let another agent finalize it.
5. Re-enable `mac-media-old` leasing only after active-job count is zero.
6. Restore the previous backend image if required. Additive `media_agents`,
   source-registry, cloud-identity, and agent-identity tables may remain.
7. Do not delete dives, cache entries, representative history, or source files.

Database baseline:
`backups/database/divesensei-pre-mac-media-node-<timestamp>.dump`.

New Mac bootstrap baseline:
`/Users/Shared/services/backups/bootstrap/mac-server-bootstrap-pre-media-<timestamp>`.

If only the frontend fails, restore the archived static frontend without
rolling back media or PostgreSQL.
