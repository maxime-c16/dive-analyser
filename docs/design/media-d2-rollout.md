# D2 rollout: lease fencing + worker keepalive/timeout (no SQL, no secrets)

D2 adds no schema (D1 columns `media_jobs.lease_token` / `finalized_slots`
are already live and NULL) and no user-visible behavior.
`Release notes: none — internal job-integrity hardening.`

## Order: SERVER first, then MAC, then enforce

1. **Server deploy** (`ci/ship.sh server --dry-run`, then `server`).
   No manual SQL. The new code reads/writes only the D1 columns; old code
   already ignores them, and the new server still serves old workers (below).
2. **Mac deploy** (`ci/ship.sh mac`) once the server is healthy. Verify the
   agent runs the new SHA and the pid is stable (ship.sh checks this); a
   lingering old worker process keeps minting tokenless leases, so the
   absence proof below must pass, not a clock bound.
3. **Absence proof, then enforce.** There is NO time-bounded drain:
   heartbeats extend the lease indefinitely (+5 min per heartbeat, unbounded
   renewals) and the 2700 s bound covers ffmpeg transcode only — not
   download/upload. Do not flip the flag after "~2 h"; flip it only after
   the query below returns `0` AND no old worker remains. Then set
   `MEDIA_JOBS_REQUIRE_LEASE_TOKEN=true` in the managed server environment
   file `~/.config/diveanalyzer/media-jobs.env` (mode `600`, same pattern as
   `calendar.env`, sourced by `ci/ship.sh` on deploy AND rollback — never a
   live manual edit) and redeploy the backend with
   `ci/ship.sh server --dry-run`, then `ci/ship.sh server --ref <same-sha> --force`.
   `--force` is required: a same-SHA ref is otherwise skipped as already
   deployed, so `--ref <same-sha>` alone does NOT apply env changes.
   From then on every lease mutation needs a token.

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

## Drain: absence proof, not a clock bound (fail-safe)

A lease does NOT expire within ~2 h on its own: each heartbeat renews it by
5 min with no cap on renewals, so a live old worker extends its tokenless
claim indefinitely; the ffmpeg 2700 s bound caps one transcode phase only,
not download/upload/finalize. The drain completes only when old workers are
gone — prove it, do not assume a bound. Before step 3, ALL of these hold:

```sql
SELECT COUNT(*) FROM media_jobs WHERE status IN
  ('claimed','materializing','exporting','transcoding','uploading','verifying')
  AND lease_token IS NULL;
```

- Expect `0` (no live tokenless claims). Nonzero means an old worker is
  still leasing — DO NOT flip the flag; check `claimed_by` and the Mac
  deployed SHA/pid. Fail-safe: enforcing while null claims exist rejects
  those workers' renewals AND their re-leases (`media_job_lease_upgrade_required`),
  stalling their jobs until they upgrade — so never force-enforce.
- Mac worker proof: `ci/ship.sh status` shows the agent code at the D2 SHA
  with a stable pid, and no pre-D2 worker process remains. Time since deploy
  is NOT evidence.

The transition flag defaults to false (drain open). The sunset is NOT
indefinite: flipping it to true after the absence proof is part of this
babysit (verify query + worker SHA, enforce with --force, re-verify), not a
later cleanup.

## Rollback (explicit ordering, both directions)

- Deploy order is SERVER then MAC: the new server serves old workers
  (tokenless drain) and new workers; the new Mac against the new server
  mints tokens. Either code rollback is safe in either order for the same
  reason (old server ignores tokens; new server serves old workers) — BUT
  the REQUIRE flag couples them:
- If `MEDIA_JOBS_REQUIRE_LEASE_TOKEN=true` is enforced: rollback MUST
  disable the flag first (`media-jobs.env` back to false +
  `ci/ship.sh server --ref <sha> --force`), THEN roll code back. Rolling
  the Mac to an old worker while the flag is still true stalls that worker
  (tokenless leases refused with `media_job_lease_upgrade_required`).
- Code: `ci/ship.sh server --ref <previous-sha>` (+ `mac` for the worker).
  The D1 schema stays (never rolled back); old code ignores the new columns
  and the per-attempt `job-<id>-<token>.partial` tmp files plus per-request
  `job-<id>-<token>.<uuid>.staging` files are simply orphaned (reclaim of
  the new code queues them for post-commit unlink; otherwise they sit in
  `tmp/` and are never promoted — finalize only promotes
  `job.upload_tmp_path`).
- Env: flipping `MEDIA_JOBS_REQUIRE_LEASE_TOKEN` back to false re-opens the
  drain window without a code change (same `--force` same-SHA rule).

## Behavioural notes for review

- Expired attempts cannot renew or write (heartbeat/upload/fail/finalize
  reject `media_job_lease_expired`); server reclaim owns expired jobs.
  Reclaim serializes with the row guards via SELECT ... FOR UPDATE (both
  orders, bounded lock timeouts); orphans are unlinked only after the
  owner's commit (a rollback resurrects the row with its bytes intact).
- Uploads stream to per-request staging and promote atomically to the
  per-attempt canonical path inside the row-locked accept: a same-attempt
  retry can never unlink or interleave the live attempt's accepted bytes
  (last writer wins; losers remove only their own staging). Stale bytes are
  rejected pre-write and removed post-hash on a mid-upload re-lease.
- Worker keepalive is monotonic: a lagging phase echo renews the lease
  without regressing status/progress (uploading never pulls verifying back,
  so a valid finalize cannot be broken by a keepalive).
- Worker keepalive spans the whole job and abandons (no fail/upload/
  finalize) once the claim is dead; shutdown-cancel never burns an attempt
  (reclaim requeues). ffmpeg past the bound is SIGKILLed, reaped, partial
  removed, source untouched, job failed with `ffmpeg_timeout`.
- Legacy `build_media_key` / job keys unchanged; `#134` retention and all
  360/720/poster serving behaviour unchanged.
