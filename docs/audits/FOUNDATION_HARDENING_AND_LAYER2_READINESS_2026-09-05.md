# Foundation Hardening And Layer-2 Readiness - 2026-09-05

Status: in-progress audit for the P0.6/P0.7 hardening packet.

## Security Closure

The PostgreSQL credential was rotated for the existing `diving` role. Runtime authority is `/home/mcauchy/dive-analyser/.env`; the credential was not written to Git or documentation. The obsolete credential was removed from reachable Git history by rewriting history with `git-filter-repo`; `.env` no longer has reachable history. Credential-bearing ignored server report documents and deployed Mac-agent archive docs were redacted.

Machine-to-machine API authentication now validates configured runtime keys with `hmac.compare_digest` and fails closed when no key is configured. The Mac agent has a dedicated random machine key, distinct from the DB credential. The backend runtime receives it via `.env`/Compose and the media-agent DB row stores only the SHA-256 hash used for per-agent authorization.

Mac-to-server privileged transport now uses `https://192.168.1.57:6443` with a local CA. The server private key remains under ignored `nginx/ssl/` on the Debian host. The public CA certificate is installed at `/Users/Shared/services/data/diveanalyzer/state/diveanalyzer-ca.pem` on the Mac and the agent passes it to curl with `--cacert`.

PostgreSQL, backend direct port, frontend direct port, and Adminer are loopback-bound. nginx remains LAN-facing on 6090/6443 for the personal app. CORS is configured from runtime origins instead of wildcard-with-credentials.

## Runtime Changes

Restarted/recreated services: backend during DB rotation and API auth deployment, nginx for TLS activation, postgres/backend/frontend/adminer for loopback port binding, and launchd `com.diveanalyzer.agent` for API key and HTTPS config. Production DB counts remained 2803 dives and 168 sessions. No media originals or Photos data were modified.

Removed orphaned containers: `dive-analyser-backend-v2-candidate`, `dive-analyser-frontend-v2-candidate`, and `dive-analyser-frontend-mac-media-candidate`. They had no Compose labels, no mounts, no restart policy, and only stale LAN ports.

Updated the SSH login banner `~/.homeserver-login.zsh` to include the current Dive Analyzer URL `https://192.168.1.57:6443`.

## Hygiene

Archived ignored root debris to `/home/mcauchy/dive-analyser-archive/ignored-root-debris-2026-09-05` with `MANIFEST.txt`. Tracked root control docs were restored after an over-broad first pass. The dead Linux `/photos_library` bind mount and `PHOTOS_LIBRARY_PATH` environment entry were removed from future Compose configuration. Compose DB defaults now match the live intended bootstrap name/user and use a non-secret placeholder password. `frontend/Dockerfile` and `frontend/Dockerfile.deploy` are intentionally both retained: the first is a dev-server image, the second is the deployed nginx build image.

## Validation Snapshot

- `git fsck --strict`: PASS after history rewrite.
- Pre/post rewrite current tree equivalence: PASS at rewrite time.
- Old DB credential reachable-history scan: PASS absent.
- Backend focused tests: 21 passed for API key, video sync, media node.
- Frontend MediaRecall test: 3 passed after stale duplicate-text assertion repair.
- Mac deployed SyncClient tests: 5 passed.
- Server-host Mac-agent tests: async tests skipped because dev dependency `pytest-asyncio` is not installed in that host environment; deployed venv has it and passes.
- HTTPS: Mac verified `https://192.168.1.57:6443/health` with CA; without CA verification fails.
- API auth: valid key 200, invalid key 401, missing key 401 on a protected endpoint.

## Off-host Backup

A sanitized bare mirror was created on the Mac at `/Users/Shared/services/data/diveanalyzer-source-backups/dive-analyser-2026-09-05.git`. It is source-only, outside the deployed Mac-agent tree, mode 0700, and `git fsck --strict` passed. It must be refreshed after the final hardening commit.

## Layer-2 Readiness

The proposal is `docs/design/ANALYSIS_LAYER_2_FOUNDATION_PROPOSAL_2026-09-05.md`. It recommends `analysis_jobs` analogous to but separate from `media_jobs`, PostgreSQL for metadata/scalars, local filesystem artifacts for heavy arrays/media-derived outputs, and first slices ordered as temporal segmentation, pairwise alignment, takeoff/trajectory feasibility, entry detection, then pose/keypoints.

## Remaining Debt

1. Migration-system consolidation remains deferred.
2. PostgreSQL role privileges are still broad because this phase preserved the existing role contract during rotation.
3. Historical sensitive state may still exist in the temporary recovery bundle until final validation deletes it.
4. External/private Git remote was not proven; Mac bare mirror is the authorized fallback.
5. Old unrelated shell startup files contain unrelated API-looking exports; not part of Dive Analyzer and not changed by this task.
6. Browser trust for the private CA is not installed system-wide; Mac agent trust is explicit via curl `--cacert`.

## Gate

`SUPERVISOR_REVIEW_AFTER_FOUNDATION_HARDENING_AND_LAYER2_DESIGN`
