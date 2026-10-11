# Performance and full-quality media audit — 2026-10-11

## Decision

The product requirement is full-quality media, including source resolution and
temporal detail. A 720p-only solution does not meet it. Fix the Library's
per-dive authorization queries and the rendition contract before evaluating
cloud hardware. A small VPS remains a plausible app/database host, with media
delivered from object storage and processing on the existing Mac.

This is an investigation, not an implementation or deployment. Production
files, settings, containers and data were not changed. Experiments ran in a
separate Python process inside the existing backend container. Database
sessions explicitly used `SET TRANSACTION READ ONLY` and rolled back.
Temporary Python function substitution affected only that investigation
process, never the serving worker. No credentials, signed URLs or user records
are included here.

## Measured environment

- Host: two-core Pentium 3550M, approximately 8 GB RAM, many unrelated services.
- Backend: one Uvicorn worker, one CPU / 512 MiB container limits.
- PostgreSQL: 53 MB database; 2,944 dives / 176 sessions at measurement time.
- Catalog: 2,927 blobs, approximately 64.32 GB. This is not a bucket billing
  inventory: replicas, versions and unregistered objects can differ.
- Largest source group: 1,808 HEVC 1920×1080 blobs averaging 18.24 MB.
- 102 HEVC 3840×2160 blobs average 73.09 MB. Other dimensions/codecs also exist.
- Media cache: approximately 1 GB; legacy local video directory: 14 GB.
- Live cache entries changed during the audit as the worker continued running.
- Public entry point: Tailscale Funnel → separate nginx proxy → app.

## 1. High: Library serialization performs an authorization query per dive

Sources: `backend/app/api/v1/dives.py:72–88,177–183`,
`backend/app/services/dive_access.py:90–104`,
`backend/app/services/user_access.py:55–70`.

`_public_dive` calls `can_manage_dive` for each row. For a linked dive this
queries `UserDiverAccess`, even though request context already contains the
current user's OWNER diver IDs. The global ORM visibility listener runs for
each of these queries too.

Read-only measurements on the deployed code, using an existing active account
and the Library's `all` / exclude-lineup filters:

| Experiment | Returned rows | SQL queries | Function wall time | SQL execution time |
| --- | ---: | ---: | ---: | ---: |
| Deployed behavior | 250 | 255 | 2.550 s | 0.350 s |
| Reuse request ownership in isolated process | 250 | 4 | 0.081 s | 0.033 s |
| Same experiment, limit 5,000 | 2,570 | 4 | 0.501 s | 0.062 s |

The two 250-row payloads compared equal. This is approximately a 31× improvement
for that measured function call. It is not a production end-to-end latency
guarantee or proof of equivalence across all authorization cases. The baseline
ran before the candidate, so cache warming can contribute to timing differences;
the eliminated query count and profile independently establish the cause.

A separate profiled 100-row baseline executed 104 queries. Of 1.577 s total,
1.490 s was under `can_manage_dive`; 1.029 s was under
`scope_member_reads`. Cumulative times overlap and must not be summed.

Recent logs contained nine slow `/api/v1/dives` requests, with a median of
73.278 s and maximum of 90.375 s. Those statistics cover slow logged requests
in a bounded last-10,000-line / last-24-hour sample, not every request. The
experiment ran under different load, without HTTP/dependency/encoding overhead;
it establishes a major cause, not a complete explanation of each 90 s request.

Repair: reuse freshly resolved request ownership for list serialization,
preserving the orphan-admin and pending-depositor cases. Validate owner,
non-owner, admin, orphan, private/public and pending/accepted deposits, plus
bounded query count as row count grows. Do not bypass visibility guards.

## 2. High: having a 720p cache copy can prevent original playback entirely

Sources: `backend/app/api/v1/media.py:129–131,393–428,1010–1038`,
`frontend/src/services/mediaApi.ts:62`,
`frontend/src/components/DiveVideoPlayer.tsx:159–170`,
`frontend/src/utils/mediaPreview.ts:127–137`.

Backend status prefers `proxy_720p` over `original`. It does not resolve the B2
original when a 720p entry exists. The player assigns `originalSrc` from that
same status `playback_url`, so it equals the startup URL; `PreparedVideo` then
skips the original-upgrade path. The preview lookup likewise only asks for
additional details when its URL is already a backbone revision URL.

Live read-only sample: ten assets with a ready 720p entry and a backbone
revision all selected `proxy_720p`, with no cloud-original URL selected. The
code explains the behavior; the sample is not an exhaustive inventory of
browser sessions.

Repair: expose distinct authorized preview and full-quality sources with
actual resolution/codec metadata. Do not label a 720p cache entry as the
original or make original availability depend on absence of a preview.

## 3. High: original quality waits for the entire video to download

Source: `frontend/src/components/PreparedVideo.tsx`, especially
`fullyBuffered`, `start`, `upgrade` and `syncSound`.

When distinct preview/original URLs exist, the player creates a hidden second
video, starts muted playback to drive buffering, and refuses to show the
original until its entire duration is buffered. It retains the preview as the
audible soundtrack and corrects the silent video's speed by ±3% to manage
clock drift. Existing `PreparedVideo.test.tsx` explicitly tests the
whole-original buffering requirement.

This is a deliberate design, but a poor match for full-quality-first playback.
An 18 MB original over an effective 10 Mbit/s link takes roughly 14 seconds to
transfer completely; a 73 MB original takes roughly 58 seconds, before other
overhead. These examples are arithmetic, not measurements of the user's link.
An unsupported original can leave the preview playing without a visible
quality failure. Two decoders and transfers also increase device/network work.

Repair: let the chosen full-quality stream play after sufficient startup
buffering. Use a poster until its first presented frame. If preview startup is
retained, expose it as a temporary quality state, and make upgrades/failures
observable. Prefer one compatible browser rendition with its own synchronized
audio. Preserve source resolution and frame rate; retain archival source bytes.

## 4. Medium: public static assets lose caching and compression

Source: `ops/tailscale/nginx.conf:17` and `/assets/` location;
`frontend/nginx.conf` immutable asset policy.

A live HEAD request with `Accept-Encoding: gzip` to the main versioned JS asset
returned 599,730 bytes, no `Content-Encoding`, and all three headers:

```
Cache-Control: max-age=31536000
Cache-Control: public, immutable
Cache-Control: private, no-store
```

The direct frontend returned the first two headers only. The Funnel proxy's
server-wide `no-store` defeats reuse of immutable assets. The tested response
was also uncompressed. This makes repeat loads needlessly expensive on mobile
and through the public proxy. It is not a claim about every asset or protocol.

Repair: route-specific cache policy for hashed public assets, while retaining
appropriate private/no-store rules for authenticated data and grants. Enable
compression for text responses, not already-compressed video. Check headers
at the actual public entry point after deployment.

## 5. Medium: the Library fetches everything and silently stops at 5,000

Source: `frontend/src/pages/Dives.tsx:269–271`,
`backend/app/api/v1/dives.py:134–135,177`,
`frontend/src/services/libraryCache.ts`.

Initial load requests 5,000 newest visible non-lineup dives. The measured
2,570-row response encoded to approximately 2.50 MB of uncompressed JSON.
The client stores and filters that snapshot. There is no next-page retrieval
in this Library load; when the visible corpus exceeds 5,000, older matches
will disappear from client search/filter results. This truncation is a growth
failure, not currently observed data loss.

Repair: cursor pagination and server-side filters/search with a small first
page, explicit completeness/count information, and bounded client storage.

The backend defines `LIST_COLUMNS` and imports `Load` but its query still
loads complete `Dive` entities. The response whitelist protects the output,
but does not reduce fetched database columns as the comment implies.
Apply a tested column-loading strategy that includes permission/DD inputs.

## 6. Medium: browser uploads tie processing, storage and database transactions together

Sources: `backend/app/api/v1/dives.py:245–383`,
`backend/app/services/browser_upload.py:17–65,82–120`.

The request copies the uploaded file, probes it, transcodes a 720p preview on
the app host, uploads the original to B2, downloads the complete original
again to verify it, then publishes the dive. This preserves an important
integrity guarantee. It also makes request duration include processing and
multiple full-file transfers. PostgreSQL rows are flushed before the remote
upload/verification completes, so that transaction and connection stay open
through external network I/O. The route is synchronous and uses FastAPI's
threadpool; it should not be described as directly blocking the event loop.

At larger concurrent upload volume, the small connection pool, shared CPU,
disk and upstream bandwidth can be occupied by uploads rather than browsing.
This was identified structurally, not load-tested against production.

Repair: separate pending upload/processing state from short publication
transactions. Direct upload plus a background verification/processing job can
retain the full-byte verification guarantee. Full-quality browser renditions
should be generated by a worker, not by weakening archival integrity checks.

## 7. Medium: browser uploads can exhaust a small VPS disk despite the cache cap

Sources: `backend/app/services/browser_upload.py:76–80`,
`backend/app/services/media_cache.py:205–235`,
`backend/app/config.py:47`.

Every browser upload pins its local source, preview and poster. Cache cleanup
only evicts unpinned entries. The default 50 GiB cache setting therefore cannot
bound browser-upload storage. Enough uploads can fill a 75 GB VPS even though
the originals are also verified in B2. The observed cache entries during this
audit were unpinned; this is a confirmed code path/growth risk, not a current
disk emergency caused by browser uploads.

Repair: explicit retention policy after verified remote persistence, disk
headroom checks, account quotas and bounded temporary storage. Never delete
the only verified original or remove an integrity guarantee to save space.

## 8. Medium: negative thumbnail status can remain stale for the session

Sources: `frontend/src/utils/mediaPreview.ts:28–31,64–68`,
`frontend/src/components/DiveThumbnail.tsx:23–53`.

Successful status responses, including missing/not-ready results, enter an
unbounded-lifetime preview map. `getPreview` returns cached results without
TTL, and the thumbnail effect depends only on UUID. If a worker subsequently
creates media, that tile can remain missing until a cache reset/page reload.
Transport failures are intentionally not inserted into the map; that existing
distinction is good. The player separately revalidates status, so this finding
does not mean playback is permanently unavailable.

Repair: short negative-cache TTL plus invalidation/refresh when media jobs
complete. Keep batch requests and avoid reintroducing per-tile request storms.

## 9. High for judging quality: evaluation transport has a different source contract

Sources: `backend/app/services/evaluation_access.py:_PLAYABLE_PREFERENCE,
media_status,prepare_media`, `backend/app/api/v1/evaluations.py:138–203`,
`frontend/src/components/evaluation/EvaluationPlayer.tsx`.

Evaluation playback considers locally ready cache entries, preferring 720p;
it does not use the Library's verified B2 original-selection path. Preparation
requests at most a 720p proxy and poster. An original existing only in B2
therefore does not provide original quality to this judging transport.
The separate authorization scope for private evaluations is necessary; the
separate quality policy is the problem.

Repair: share rendition/source-selection semantics across Library, evaluations
and shared clips while retaining each scope's explicit access checks. An
evaluation-specific authorized original grant is an implementation option;
do not reuse a Library route that correctly rejects another user's private
evaluation dive.

## Design feedback and order of work

The app has substantial integrity and access-control safeguards. The most
visible performance problem is repeated policy work, not the size of its
database. The global ORM listener builds visibility criteria across the
mapper registry even for a tiny ownership lookup; its cost multiplies with
per-row authorization. Remove repeated work first, then profile whether
model-specific scope construction is justified. Do not globally remove the
listener without equivalent privacy coverage.

The media code calls 720p "HQ" in several different paths. That vocabulary
hides a product mismatch. Define archival source, browser-compatible
full-quality rendition and optional fast preview as separate capabilities.
Include resolution, codec, frame-rate and quality state in that contract.
HEVC support depends on browser/device; a high-resolution compatible rendition
may be needed without dropping the preserved original. Actual device playback,
HDR handling, frame-rate preservation and seeking remain unverified here.

Priorities:

1. Fix the list's repeated ownership lookup; add authorization and query-count
   regression coverage. Re-measure real HTTP latency and payload size.
2. Repair preview/original discovery and bring evaluations onto the same
   full-quality contract.
3. Replace whole-file-gated upgrading with observable full-quality streaming.
4. Repair public asset caching/compression, then paginate the Library.
5. Separate upload jobs from publication transactions and establish retention.
6. Trial a small cloud app/database host using direct HTTPS and object-storage
   media delivery. Preserve the Mac worker and add database backup/restore checks.

Adding Uvicorn workers is not currently a safe drop-in scaling fix: compose
documents process-local WebSocket and playback metrics state. Shared event
coordination would be needed. A paid CDN, HLS/DASH or Kubernetes is not required
to address the confirmed failures; assess those only against measured quality,
startup and bandwidth needs.

## Limits

This was a focused live read-only and source audit, not a complete security
review, browser/device test or concurrent load test. Timings are individual
samples. Equality was checked for one real account's 250-row payload, not the
entire permission matrix. No application patches, purchases or deployments
were performed. The service continued changing media counts while inspected.
