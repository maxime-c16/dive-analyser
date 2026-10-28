# Shared sessions (steps 1 + 2)

Goal: replace "trim clips by hand in iOS Photos + share an iCloud link" with:
film the whole session → the raw video lands in B2 by itself → a session page
and a guest share link exist → club members watch it in the app (later: mark
their dives and export clips — steps 3–4, NOT in scope here).

## Decisions already taken (do not reopen)

- **Phone → B2 is solved outside the app**: Maxime uses the iOS app *S3 Files*
  (Files-app location on the bucket) and saves the video from the Photos share
  sheet into `diveanalyzer-sessions/inbox/`. Field-tested 2026-10-28: 3.34 GB
  in ~13 min, survives screen lock and Wi-Fi→5G→Wi-Fi, byte-identical. Uploads
  are S3 multipart with 5 MB parts.
- **No transcoding owned by us.** Serve the iPhone original as-is (most of the
  club is on iPhone). Files are HEVC, often 10-bit HDR (HLG + Dolby Vision),
  1080p60, ~13–14 Mbit/s, 30–75 min, 3–8 GB. Do not build a proxy pipeline.
- Devices that can't play it get exactly this UI, nothing more (no VLC/format
  advice — product rule: cut helper text):
  **« Cette vidéo ne se lit pas ici »** + button **« Télécharger · <taille> »**.
  Detect with MediaCapabilities/`canPlayType` for the stored codec string *and*
  a runtime check that frames actually render (Chrome can play audio over a
  black frame). Count these events server-side (no UI) to know how often it
  happens.
- **Arrival detection = B2 Event Notifications** (GA; signed HTTP POST,
  at-least-once, retries) **plus a reconciliation poll of `inbox/` every
  10 min** as a safety net (the public URL goes through Tailscale Funnel, which
  has dropped after WAN cuts — see ops/funnel-watchdog.sh). Ingestion must be
  idempotent: one object → one session video, whatever the number of events.
  Look up Backblaze's official docs for the exact signature header/scheme and
  event type names; verify HMAC on the raw body with a constant-time compare.
- **Metadata without downloading**: deb-serv's disk is ~96 % full and slow. Run
  `ffprobe` against a short-lived presigned GET (range reads of the moov atom
  only) to get duration, codec/profile, pix_fmt, transfer (HDR), resolution,
  fps, creation date (`com.apple.quicktime.creationdate`). Never copy the file
  to the server. Strip/ignore GPS (`ISO6709`) — never expose it.
- **Session = training day**: attach the video to the existing `sessions` row
  for the recording's local date (Europe/Paris), creating it if missing.
  New table for the videos (do not overload `sessions`).
- **Notifications on ingest**: Telegram (reuse the funnel watchdog bot; its
  token/chat id live in `/etc/dive-funnel-watchdog.env` on deb-serv — the
  backend needs its own env entries, never in Git) **and** in-app inbox + Web
  Push through the existing `notification_service`/`push_service` to the
  owner. Message contains the share link.
- **Guest share link**: same model as the existing dive sharing
  (`docs/guest-dive-sharing.md`, `backend/app/api/v1/dive_sharing.py`): secret
  in the URL fragment, only hashes stored, revocable, guests get a random
  film-character identity cookie. Reuse, don't fork, wherever possible.
  Playback for guests and members = short-lived presigned B2 GET (redirect),
  like `media_playback.py`; large files must support Range/seek (B2 does).
- **Owner**: sessions belong to Maxime's account (configurable owner email,
  like `INGEST_DEPOSITOR_EMAIL`). Feature flag default OFF.
- Separate small PR: **iOS Web Push fix**. Prod has zero iPhone push
  subscriptions (only 2 MacIntel). Likely cause:
  `frontend/src/services/pushSubscription.ts` `enablePushDevice` awaits
  `serviceWorker.register()` before `Notification.requestPermission()`, which
  loses iOS Safari's transient user activation → silent denial. Request
  permission first (synchronously inside the click), then register/subscribe.
  iOS also requires the installed home-screen PWA; keep that hint in the UI.

## Infra facts

- Bucket `diveanalyzer-sessions` (B2 EU-Central 003, private, endpoint
  `https://s3.eu-central-003.backblazeb2.com`). `lab/` = old test uploads
  (30-day lifecycle). `inbox/IMG_2651.MOV` (3.34 GB, HEVC HDR, 32 min) is a
  real test video — keep it.
- CORS already allows `https://dive-analyser.tail32dd14.ts.net` and
  `http://192.168.1.151:8791` (browser playback/download only needs GET).
- A bucket-scoped key (read/list/write/delete) is in
  `~/.config/dive-analyser/session-lab.env` on Maxime's MacBook (mode 600,
  vars `SESSION_LAB_*`). Use it **read-only** for local testing; never commit
  it, never print it. Production gets its own read-only key later (Maxime).
- The prod media key (`B2_UPLOAD_*`) is prefix-locked to `blobs/sha256/` of
  the prod bucket: never use it for sessions.
- Deploy rules: `docs/REPO_WORKFLOW.md` and `AGENTS.md`. SQL migrations are
  applied by hand before `ci/ship.sh`; new runtime secrets go in a new
  `~/.config/diveanalyzer/<name>.env` on deb-serv loaded by `ci/ship.sh` and
  wired in `docker-compose.yml`.
- Reference prototype of the direct-upload protocol (not needed for this PR,
  kept for later): `tools/session-upload-lab/`.

## Implementation (steps 1 + 2)

- **Ingestion** — `backend/app/services/session_videos.py`. Identity = unique
  `(bucket, object_key)` row in `session_videos`. A conditional UPDATE claims
  the probe (`pending`, stale `probing` > 15 min, or `failed` with < 5
  attempts), so duplicate events, the reconciliation and several processes
  converge on one row and one ffprobe. A second conditional UPDATE on
  `notified_at` sends the owner notification exactly once. No SQL transaction
  is open during B2/ffprobe work; at most 2 probes run at once.
- **Arrival** — `POST /api/v1/session-videos/b2-events` verifies
  `X-Bz-Event-Notification-Signature: v1=<hex HMAC-SHA256(raw body)>` in
  constant time (401 otherwise), accepts `b2:ObjectCreated:*` events for the
  configured bucket under `inbox/` with a `.mov/.mp4/.m4v` name, answers
  immediately and ingests in the background. `b2:TestEvent` is acknowledged.
  The reconciliation thread lists `inbox/` 15 s after startup then every
  `SESSIONS_RECONCILE_SECONDS` (600), bounded to 2 000 listed keys and 20
  ingestions per pass.
- **Metadata** — ffprobe on a 10-minute presigned GET (range reads, ~7 s for
  the 3.3 GB test file). Stored: duration, codec + RFC 6381 codec string
  (`hvc1.2.4.L123.B0`), profile, pix_fmt, transfer (`arib-std-b67` = HLG),
  size, resolution, fps, bitrate, recording time. The day is the Europe/Paris
  date of `com.apple.quicktime.creationdate` (fallback `creation_time`, then
  B2 upload time). Location tags are never read.
- **Session** — the video is attached to the `sessions` row of that day,
  created if missing.
- **Playback** — `GET /api/v1/session-videos/{id}/play` (any signed-in
  member) redirects to a presigned GET of the original with
  `response-content-type=video/mp4` (lets Chrome try the QuickTime file); TTL
  `SESSIONS_PLAYBACK_TTL_SECONDS` (4 h) because one URL serves all the Range
  requests of a long session. On a network error the player requests a fresh
  URL and resumes at the same time. `/download` adds
  `Content-Disposition: attachment`.
- **Unplayable devices** — the player checks MediaCapabilities (else
  `canPlayType`) for the stored codec string, then after 1.5 s of playback
  checks that frames were rendered (`videoWidth`, `getVideoPlaybackQuality`).
  On failure it shows only « Cette vidéo ne se lit pas ici » + « Télécharger ·
  <taille> » and posts the reason (`unsupported`, `no_frames`, `error`) to
  `session_video_playback_issues` (one row per viewer/video/reason/hour). Query:
  `SELECT reason, count(*) FROM session_video_playback_issues GROUP BY 1;`
- **Guest links** — `session_video_shares` (hash only, revocable by owner or
  admin). Guest API lives under `/api/v1/shared-dives/sessions/{share}/…` so
  the existing guest cookie, film-character identity and Funnel rule apply
  unchanged; the page is `/share/session/{id}#<secret>`.
- **Notifications** — inbox row type `session_video` (push opens
  `/session-videos/{id}`). When Telegram is configured, a guest link is issued
  automatically and sent with the member link; its secret exists only in that
  message.

### Choices made where the spec was silent

- Members = every active signed-in account (friends included); sharing is
  reserved to the owner and admins.
- The in-app inbox and push carry the member link, not the guest secret
  (inbox rows are stored in clear); the guest link goes to Telegram only.
- One object key = one session video. Re-uploading under the same name does
  not create a second video.
- No preference toggle for `session_video` (owner-only alert).

## V2 — decisions from Maxime's review of the first test build (2026-10-28)

### PR A v2 (this branch, PR #178)
- **A link = a session, not a video.** 2–3 videos of the same session are
  common; a video uploaded later shows up under the same link.
- **Session page, mobile first, no scrolling needed**: header (date · N
  videos · total duration), video thumbnails (one poster per video + start
  time + duration), primary button **« Tout télécharger · <taille> »**. Tap a
  thumbnail → the video plays in the existing library player look; the other
  videos stay reachable as a strip. Reuse library cards/player components,
  not a bespoke rudimentary page. No autoplay (guests on 4G).
- **Download all**: members download each file in turn (no server-side zip,
  deb-serv disk is full); also a per-video download in the player. Guests see
  the button with a lock → tapping opens account creation.
- **One link for everyone = invitation + login.** Existing account → log in
  and land on the session. New person → short onboarding: credentials (name,
  email, password) + club → training group (they pick the group; existing
  `TrainingGroup`/`TrainingGroupMembership`) → creates a real **diver**
  account (role diver + Diver profile), never "friend". Then a message says
  they will get an email for their group's next sessions, with the toggle
  shown and **on by default**, changeable later in the account. Revoking the
  link also stops signups through it. Each signup through a link notifies
  Maxime on Telegram (+ inbox) so he can deactivate strangers.
- **No duplicate divers**: if the new name matches an existing account-less
  Diver profile (e.g. deposited clips; MAT/Mat duplicates exist), queue a
  link-to-existing-profile suggestion that Maxime validates (admin), instead
  of silently creating a second profile or auto-merging.
- **Library**: sessions are mixed with dives in the library feed, with a
  distinct card (badge « Séance », video count, total duration), without a
  separate navigation entry or filter (iPhone review follow-up). The card uses
  the existing animated stop-motion
  thumbnail look: ~10 frames per video extracted from B2 by range reads
  (ffmpeg over a presigned URL, HDR tone-mapped to SDR JPEG/WebP), never a
  full download or transcode. Posters use the same extraction.
- **Owner settings** (owner/admin): hide/delete a wrong video, move a video to
  another session, revoke/regenerate the link.
- **Friends** (role) see sessions in the app (read only).

### PR C (separate, after A) — calendar
- Maxime (admin) assigns users to training groups; new accounts pick theirs
  at onboarding (A). Group membership = attending by default. The only RSVP
  action becomes **« Je ne viens pas »** (decline); remove the
  interested/maybe confirmation flow (built in PR #170) — reuse the existing
  absence/decline storage.
- Tie each session video to the calendar occurrence whose time window
  contains the recording time (Apple creationdate, Europe/Paris, with a
  tolerance margin); fall back to day grouping. Session title then comes from
  the event (« Entraînement jeu. 18h · <lieu> »).
- When a session's first video arrives, notify every group member who did
  not decline (in-app + push + email if their toggle is on) with the session
  link.

### PR A v2 — implementation choices and operations

- Session routes use `/sessions/shared/:sessionId`; old member video URLs still
  resolve to their session. Existing guest links are backfilled with a stable
  `session_id`; moving/deleting their original recording does not move the link.
- Hide is reversible. Delete removes the recording from the app (a tombstone);
  neither action writes to B2. Owners can still inspect hidden recordings.
- An ambiguous signup creates the account and group membership, but waits for
  an admin to attach the existing Diver. The admin directory displays the
  review queue; acceptance never steals a profile already linked to an account.
- The email preference is stored now; delivery for calendar sessions remains
  PR C. No RSVP or event-association logic changes in A.
- Feeds page 20 sessions, with bulk metadata/aggregates (six SQL queries,
  independent of page size). Recording pages contain 100 videos, with a cursor;
  totals cover all visible recordings and download-all follows every page.
- Images are local WebP derivatives: ten input seeks through a loopback range
  relay, upstream ranges capped at 512 KiB and a 128 MiB aggregate reservation
  budget per extraction. Non-206 upstream responses are rejected without
  consuming their body. No original is stored locally; HDR needs ffmpeg
  `zscale` + `tonemap`. The real 3.34 GB video used at most 72.4 MB of ranges.
- Apply `add_session_videos.sql` then `add_shared_sessions_v2.sql` before the
  backend update, even if the flag remains off (the latter adds an AppUser
  preference column). Requires the calendar domain migrations for clubs/groups.
  Existing sessions env remains sufficient; no additional secret/env variable.
  Preserve the media-cache volume for `session-images/`. Rebuild backend and
  frontend together; FFmpeg in the backend image must include libzimg.

### PR C — implementation and operations

- Expected attendance is the effective group assignment on the occurrence's
  local date, minus active absence reports and legacy `declined` answers.
  Existing `interested` / `maybe` rows are preserved without counting as
  confirmation. The old interest API remains compatible; the app offers only
  absence and cancellation. Cancellation also clears a legacy decline.
- With the calendar enabled, ingestion selects published, scheduled, timed
  group training within 30 minutes of the recording time. An exact window
  wins over the margin; then nearest start, then occurrence ID breaks ties.
  Cancelled/draft/all-day events are excluded. Unmatched videos retain day
  grouping. Historical ready videos and existing links are not rewritten.
- `sessions.calendar_occurrence_id` identifies a training occurrence; the
  existing `event_occurrences.filmed_session_id` links back to its session.
  Date uniqueness now applies only to fallback days. All dive-day writers
  explicitly select that fallback identity, so two trainings on a date do
  not mix their recordings or change ordinary dive sync/import behavior.
- Group notifications happen once for the first ready video, with a direct
  session link in the inbox, push and optional email. A session lock and a
  persisted account cursor commit inbox rows in batches of 100; subsequent
  videos/reconciliation events resume without duplicates. Push and SMTP are
  best-effort attempts after commit, without automatic transport retries.
- Apply `add_session_calendar.sql` after A's migrations and the calendar
  migrations, before updating **backend and frontend**. It is idempotent,
  preserves every RSVP row, and needs no new secret, timer or Mac service.
  Existing `CALENDAR_ENABLED`, shared-session and SMTP settings apply.
  The existing Administration > Clubs screen assigns accounts to groups.
- Backout must keep the schema and data. Do not restore global date
  uniqueness or run A's backend against multiple same-date sessions; use a
  forward fix or disable the feature while retaining this backend. There is
  no destructive RSVP conversion to reverse.
