# D2 rollout: lease fencing + worker keepalive/timeout (no SQL, no secrets)

D2 adds no schema (D1 columns `media_jobs.lease_token` / `finalized_slots`
are already live and NULL) and no user-visible behavior.
`Release notes: none — internal job-integrity hardening.`

## Order: SERVER first, then MAC, then enforce

1. **Server deploy** (`ci/ship.sh server --dry-run`, then `server`).
   No manual SQL. The new code reads/writes only the D1 columns; old code
   already ignores them, and the new server still serves old workers (below).
2. **Mac deploy** (`ci/ship.sh mac`) once the server is healthy.
3. **Drain wait** (~2 h, see below), then set
   `MEDIA_JOBS_REQUIRE_LEASE_TOKEN=true` in the server environment and
   restart/redeploy the backend (`ci/ship.sh server --ref <same-sha>`
   applies env changes). From then on every lease mutation needs a token.

No global API stop is needed at any step: during 1–2 the server speaks
both protocols (negotiated per lease), and step 3 is an env flip, not a
code deploy.

## Compatibility mechanism (negotiated, bounded)

- The lease request carries `supports_lease_token` (default false = old
  worker). A capable worker gets `lease_token = uuid4().hex` per claim and
  echoes it on heartbeat/fail/upload/finalize.
- An old worker gets a tokenless (`NULL`) lease and keeps working — but a
  missing token is accepted **only while the stored claim is itself
  tokenless**. A tokened claim with a missing token is a mismatch (there is
  deliberately no "same agent may omit" allowance).
- After step 3 (`..._REQUIRE_LEASE_TOKEN=true`): tokenless leases are
  refused at claim time (`media_job_lease_upgrade_required`) and tokenless
  mutations against leftover tokenless claims are refused
  (`media_job_lease_token_required`). The token is never optional afterwards.

## Bounded drain (not a stop)

A lease lives at most `lease_seconds` (≤ 3600 s) plus 5-minute heartbeat
extensions; the ffmpeg bound (2700 s) caps the longest phase. After the Mac
deploy, every live claim turns over within ~2 h: old claims expire →
reclaim clears them → capable workers re-lease with tokens. Verify before
step 3:

```sql
SELECT COUNT(*) FROM media_jobs WHERE status IN
  ('claimed','materializing','exporting','transcoding','uploading','verifying')
  AND lease_token IS NULL;
```

Expect `0` (no live tokenless claims). A nonzero count means an old worker
is still leasing — do not flip the flag; check `claimed_by`.

## Rollback

- Code: `ci/ship.sh server --ref <previous-sha>` (+ `mac` for the worker).
  The D1 schema stays (never rolled back); old code ignores the new columns
  and the per-attempt `job-<id>-<token>.partial` tmp files are simply
  orphaned (reclaim of the new code removes them; otherwise they sit in
  `tmp/` and are never promoted — finalize only promotes
  `job.upload_tmp_path`).
- Env: flipping `MEDIA_JOBS_REQUIRE_LEASE_TOKEN` back to false re-opens the
  drain window without a code change.

## Behavioural notes for review

- Expired attempts cannot renew or write (heartbeat/upload/fail/finalize
  reject `media_job_lease_expired`); server reclaim owns expired jobs.
- Upload tmp paths are per attempt; stale bytes are rejected pre-write and
  removed post-hash on a mid-upload re-lease. Reclaim unlinks orphans
  best-effort.
- Worker keepalive spans the whole job and abandons (no fail/upload/
  finalize) once the claim is dead; shutdown-cancel never burns an attempt
  (reclaim requeues). ffmpeg past the bound is SIGKILLed, reaped, partial
  removed, source untouched, job failed with `ffmpeg_timeout`.
- Legacy `build_media_key` / job keys unchanged; `#134` retention and all
  360/720/poster serving behaviour unchanged.
