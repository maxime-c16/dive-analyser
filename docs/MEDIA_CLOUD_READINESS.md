# Full-resolution media and a €50 monthly budget

This rollout keeps the existing server and B2 accounts. No hosting order,
DNS change, new provider account or cloud migration is part of these PRs.
The library and player fixes must be measured before buying extra CPU.

## Playback contract

Library and jury playback prefer a ready original, then the verified PROD
B2 original, then an explicitly labelled cached preview. A local 720p proxy
must never hide an available original. Source discovery keeps the existing
authentication and B2 playback feature gates; each actual playback request
checks current authorization and storage authority.

The player uses one native video element for picture and sound. It starts
streaming immediately; it does not wait for an entire hidden original to
buffer. Neighbor preparation loads metadata, with at most three speculative
elements, and respects Save-Data. Originals retain their source codec: HEVC
support still depends on device/browser. Decode failures offer an explicit
preview action. Native HEVC/HDR playback must be checked on the actual target
iPhone, Android and desktop browsers; unit tests do not prove codec support.

Evaluation grants remain restricted to active requests. B2 URLs appear only
in redirects, expire within 300 seconds, and are never saved in payloads,
logs or SQL. Deactivating a request prevents new grants immediately; a prior
signed link/browser cache can remain usable for up to five minutes.

New browser uploads archive their untouched source AND a separate full-size
H.264/AAC faststart MP4, both uploaded and roundtrip SHA-256 verified before
publication. No 720p cap or frame-rate reduction is applied. The compatible
MP4 is a high-quality CRF-18 encode, not bit-identical to the source. PQ/HLG
HDR is tone-mapped to SDR for browser compatibility; the archived source
retains all original color data. Odd dimensions round down to even pixels.
New uploads are bounded to 1 GiB, three minutes, and 4K pixel area; the
compatible encode is capped at 2 GiB. Existing uploads are not re-encoded
by this deployment. Their archived untyped sources are not advertised as a
browser-ready MP4: existing preview-only uploads remain labelled previews.

## Durable uploads and retention

Apply `backend/migrations/add_browser_upload_jobs.sql` before rollout. It is
additive and can remain installed on rollback. The backend starts one queue
thread per process; a PostgreSQL session advisory lock serializes ingestion
across processes. No SQL transaction stays open during file copies, ffmpeg,
B2 upload or verification. Account state and diver ownership are checked
again before the short publication transaction. Retry identities belong to
one account; job status never reveals another account's upload.

At most two pending uploads per account and eight globally are reserved
before receiving bytes. The JSON reservation endpoint does not accept a file;
the old multipart endpoint returns 410 without parsing its body;
a separate raw PUT streams into its reserved file and enforces the byte cap
even when Content-Length is missing. Both proxies disable request buffering
for this path. Reload LAN nginx and recreate the Funnel proxy after rollout. Disk headroom reserves four GiB per pending clip
plus one GiB margin. An interrupted receiver fails after an hour; interrupted
processing resumes when the old process releases the advisory lock. Three
interruptions produce a retryable failure. Completed staging files are
removed; verified local source copies expire after one day, prepared playback
and posters after 30 days when authenticated PROD B2 playback is configured
and enabled. Otherwise playback/posters remain pinned, including before
cleanup if the operator disables that path later. Re-enabling flags does not
silently unpin previously protected copies. Unpinned files obey the configured
media-cache byte cap. The worker runs cleanup at most every ten minutes when
idle, removing up to 100 expired entries and 100 entries above the byte cap
per pass. Larger backlogs need multiple passes. Set the cache cap below disk
capacity and leave at least five GiB free for one upload reservation; free
space admission checks remain authoritative. Archived source and full-resolution MP4 stay in B2. Existing pinned
entries are retained; this rollout does not silently change their retention.

Queue metadata persists in Postgres and staged bytes live under the existing
persistent media-cache volume. Back up both together. A CPU-limited worker
can take minutes to prepare a large 4K clip; it remains a visible queued job
and does not block library requests or retain a publication transaction.

## Measure, then migrate

Record warm/cold library latency, authorized source-status latency, time to
first frame, source bytes streamed, queue wait/preparation time, cache usage,
free disk and actual B2 transfer/storage bill for at least a week. Test large
4K clips and actual mobile networks, not only synthetic small MP4s.

Treat €50 as a total VAT-inclusive ceiling. A planning envelope, not a vendor
quote: €20 compute, €10 object storage/transfer, €5 backups, €15 contingency.
Check current provider pricing and transfer terms before purchasing. Track
full-resolution traffic as `plays × average source bytes`; repeated watches,
seeks, metadata prefetch and upload verification add traffic. Configure
provider spending alerts before a trial, and keep an exit/restore plan.

Trial a single EU VPS with backend, frontend and Postgres and retain private
B2 object storage. Start with one backend process and one ingestion worker;
measure before increasing concurrency. Restore a recent DB backup into the
trial, mount a persistent cache/staging volume, copy only required media,
configure existing secrets outside Git, apply migrations, and run the normal
CI gates. Verify ownership, revoked evaluations, byte-range responses,
full-resolution startup, upload recovery after restart and disk cleanup.
Switch DNS/traffic only after the restore and rollback rehearsal succeeds
and a current VAT-inclusive bill estimate fits the budget. The current server
continues running until that separately authorized cutover.
