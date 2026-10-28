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
