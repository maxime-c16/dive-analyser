# Two-slot activation and cache inventory

At 20:11:36 UTC, the Mac restarted successfully at worker SHA `e2f2654` with
`media.max_jobs=2`, using `ci/ship.sh mac --force` after a dry run. PID 54284
remained stable, last exit 0. One daemon identity remains active; Photos exports
are serialized. No second Mac or duplicate daemon was introduced.

The checked live policy enforces a **5 GiB** internal processing reserve,
not the runbook's default 18 GiB. The runtime configuration already differed
from defaults before this change; no storage threshold was lowered.
`ops/media-worker-slots.py` requires at least max(existing stop, 8 GiB) plus
2.5 GB peak-work headroom to activate two slots. It defaults to dry run, validates
the complete config, preserves a 0600 backup, and refuses concurrent edits.
The 8 GiB allowance is an activation check; ongoing processing still uses the
existing live configured reserve. It is not a per-job source-size enforcement.

Five resource samples over one minute showed up to 165.3% CPU (1.65 cores)
and 1.58 GB aggregate worker/ffmpeg RSS, with at least 13.23 GB free.
All five HTTPS API-health probes before and after returned 200; observed
before times were 10–32 ms, after 9–266 ms. These small samples do not establish
an API latency improvement or measure media grants or browser first frames.

The [two non-overlapping two-minute windows](two-slot-windows-2026-10-20.json)
contain just one completed background upgrade each. One-slot queue/processing:
26.92/14.26 s; two-slot: 18.91/15.60 s. Clips differ, and simultaneous execution
of two production jobs was not observed. Do not infer a speedup from these
numbers. Two slots are enabled for ordinary traffic, with capacity benefit
still unmeasured under a representative backlog. Revert via the slot tool
with `--slots 1 --apply`, then the same dry-run and managed worker restart.

## Cache repair inventory

The [read-only inventory](cache-inventory-2026-10-20.json) covers 2,582 distinct
public assets with a matching public, non-lineup dive:

- 1,350 missing local preview files; 1,771 missing posters.
- 764 complete local packages; 1,818 assets missing at least one component.
- 1,812 repair candidates have a verified production replica; 1,812 have an
  active Photos identity. These are separate counts; six have no known source. Four latest preview failures
  mention an invalid Photos identity.
- About 33.47 GB of known source bytes and six unknown source sizes.
  Estimated missing output at catalog median: 1.62 GB. This excludes source
  peak space, HDR replacements, transfer overhead and growth.
- All 12 sampled preview streams retain HDR transfer tags. This is a bounded,
  deterministic sample, not a population estimate or a visual color diagnosis.
  1,224 preview entries predate the HDR fix, which alone does not prove damage.
- 19 of 23 owner groups lack some packages; 13 have no complete package.
  No identities, object URLs, storage paths or credentials are published.

File presence and size are checked under the configured cache root. Only the
12 sampled previews receive ffprobe metadata checks; checksums, full decode,
posters and all other previews are not verified by this inventory. It creates
no jobs, changes no database state and does not treat catalog readiness as a
universal playback guarantee. Verified replicas are catalog evidence, not fresh
B2 network probes. Counts differ from the earlier audit because this scope
uses canonical assets with matching public non-lineup dives and actual files.

The source-vault dry run found zero eligible expired/finalized files and zero
reclaimable bytes. The Mac has about 12.4 GiB free; the server about 46 GiB.
Broad historical repair remains paused under the operations guide's 30 GiB
projected-free-space rule. No original, proxy, Photos file or cache entry was
deleted or replaced. A future bounded repair should prioritize interactive work,
verify each generated preview/poster before swapping, preserve originals, and
resume idempotently. Durable ingestion readiness remains the next implementation
stage; this inventory is not a durable-package implementation or repair run.

## Reproduction

Run the inventory on backend stdin using the command pattern in
`ops/media-playback-snapshot.py`. The snapshot now accepts timezone-qualified
`--since` and `--until`, filters both job creation and completion for an explicit
start, and rejects reversed, timezone-free or future windows. This avoids
presenting overlapping rolling windows as independent before/after evidence.
Run the slot controller with the deployed Mac Python and its code as PYTHONPATH;
never copy configuration or its backups into Git. Review the JSON plan first.

Review follow-up: database reads use keyset batches of 250 canonical public
assets; cache reads are scoped to each batch and streamed. Latest preview
failures use one indexed per-asset lookup, not a full-history window rank.
The output estimate uses public-cache medians only. A repeat read-only run
verified the scoped queries against production; ordinary ongoing upgrades can
change cache counts between snapshots.
