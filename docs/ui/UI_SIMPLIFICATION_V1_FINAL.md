# UI Simplification V1 — Final Architecture (start here)

> Closed by `UI-U8 — FINAL_USABILITY_PERFORMANCE_REGRESSION_CLOSURE_V1`.
> Durable audit: `docs/audits/UI-U8-final-usability-performance-regression-closure-v1.md`
> Prior gates: `docs/audits/UI-U0R-*.md`, `UI-U1U2-*.md`, `UI-U3-*.md`,
> `UI-U4U5-*.md`, `UI-U6-*.md`, `UI-U7-*.md`.

## Product principle: CLIP_FIRST

The app is a professional clip-review instrument, not a dashboard collection.
The normal loop is: Library → find clip → open → play → Next/Previous →
optionally Details → optionally Analysis → Back to the exact Library context.

## Final IA

- PRIMARY: Library (`/dives`; `/` redirects there query-preserved).
- SECONDARY review group: Overview (`/dashboard`), Journey (`/journey`),
  Analytics (`/analytics`), Representatives (`/media/representatives`),
  Sessions (`/sessions`).
- OPERATIONS (collapsed disclosure): Media recall (`/media/recall`),
  System (`/admin`).
- Hidden operational: Player canary (`/media/p5-canary`, B2 diagnostic
  harness consumer — reachable, never in nav).
- Compatibility: `/competitions` → query-preserving redirect to `/journey`.
- Auth: `/login`. Fallback: real 404 with Back to Library.

## Core workflow contracts

- Library (`frontend/src/pages/Dives.tsx`): structured search, scope,
  filters, grid/list view in URL params; pagination depth + exact scroll
  restoration; distinct loading / empty (Clear filters) / error (Retry).
- Clip identity: `clip=<attempt-id>` (stable DB id). Open = history PUSH,
  Next/Previous = REPLACE, Back/Close = exact Library restoration.
  Reload reopens; invalid clip fails safe.
- Viewer (`components/clip-viewer/`): video-first full-viewport modal over
  the mounted Library; native controls; 0.25x–2x rate (session-persisted);
  Previous/Next over the current filtered result with N/TOTAL and boundary
  disabling (no wrap); Details collapsed by default; Analysis is a
  secondary link with exact return.
- Keyboard: Escape closes; Shift+ArrowLeft/Right navigates clips (guarded
  against typing targets); Space plays/pauses off interactive controls;
  plain arrows stay native (seek).
- Analysis (`/dives/analysis/:code`, `pages/DiveAnalysis.tsx`): secondary
  inspection surface. Optional `?attempt=<id>` is presentation-only
  context, never computation. Aggregates are DIVE_CODE_AGGREGATE under
  active filters; attempt-vs-aggregate grain is always labeled.
  Collapsed sections mount on demand. Transport errors (Retry re-reads)
  are separated from capability states (available/partial/unavailable).
  Back-to-clip restores the exact Viewer; direct code-only URLs fall back
  to `/dives?q=<CODE>`; invalid `attempt=` never claims a clip.
- Sessions (`pages/Sessions.tsx` + `components/SessionDetail.tsx`):
  secondary day-grouped history; SessionDetail is a modal dialog with the
  same focus contract as the Viewer (inert background, Tab trap, Escape,
  focus return). Analysis AttemptDrawer is a JUSTIFIED_SECONDARY_PLAYER:
  in-context historical-attempt inspection inside the aggregate workspace
  (mounts video only on explicit open; Prev/Next over the aggregate list).

## Async / reliability contract

- Media lifecycle (`DiveVideoPlayer.tsx`, frontend-only policy; backend
  lifecycle untouched): explicit phase machine
  (checking/ready/preparing/prepare-failed/not-cached/transport-failed).
  Initial status: 3 bounded auto-retries → actionable Retry (never POSTs
  prepare on failed GET). Poll: transient failures show honest stale state;
  5 consecutive failures stop the loop with manual re-check; 90s+ legitimate
  preparation stays non-failed with manual check. Decode failure offers
  in-place reload. Prepare/Retry-prepare explicit and duplicate-guarded.
- Library/Analysis reads: error + Retry that only re-reads (never mutates).

## Mobile / accessibility contract

- Genuinely usable at 390x844, ~320px, and 844x390 landscape: no page-wide
  horizontal overflow, critical actions reachable.
- 200% zoom reflow equivalent validated.
- Skip link, single `main#main-content` landmark, viewer/dialog semantics
  with background inerting (`utils/a11y.tsx`: `inertExcept`, `trapTabKey`),
  focus trap + focus return, `role=status`/`role=alert` async semantics,
  reduced-motion enforcement, non-color state signals, >=44px targets.
- Automated axe: 0 critical / 0 serious on Library, Viewer ready/error,
  Analysis available/unavailable/progression-open, mobile Viewer/Analysis
  (region rule disabled with standing rationale; remaining moderate/minor
  dispositioned in the U8 audit). Manual screen reader: not performed
  (no operable screen reader in the validation environment).

## Visual-system authority

- `--app-*` tokens in `frontend/src/index.css` are the single product-wide
  authority. Remaining literal colors are justified only as semantic state,
  data-visualization series, or contrast requirements (documented in U6/U8
  audits). Legacy gray/cyan page themes, `sync.css`, `App.css`, and the
  `diving` Tailwind palette were removed in U6.

## Component ownership

- App shell/nav/router/breadcrumbs: `router.tsx` (CORE).
- Library + clip cards/rows: `pages/Dives.tsx` (CORE).
- Clip Viewer: `components/clip-viewer/` (CORE); player:
  `components/DiveVideoPlayer.tsx` (CORE); shared attempt formatting:
  `utils/attemptPresentation.ts`; preview cache: `utils/mediaPreview.ts`.
- Analysis: `pages/DiveAnalysis.tsx` (SECONDARY, attached to review).
- Sessions/SessionDetail: secondary history (SECONDARY).
- Dashboard/Journey/Analytics/Representatives: SECONDARY surfaces.
- Media Recall/Admin/P5 canary: OPERATIONAL.
- Shared async state: services/api + hooks; shared a11y: `utils/a11y.tsx`.

## Operational routes (not product)

`/media/recall`, `/admin`, `/media/p5-canary` — diagnostics and system
only. Never in primary nav; never part of the review loop.

## Known intentional debt (non-core)

- No dedicated low-privilege E2E identity yet: suites reuse the stored
  personal-operator session (expires 2026-10-13) with zero-login reuse.
  Safe provisioning path exists (server-local `manage_user.py create-user`)
  but needs one interactive operator getpass step. See U8 audit.
- Lint not configured (pre-existing, all gates).
- Manual screen-reader pass not performed (no operable SR in environment).

## Deployment procedure (authoritative — U8 freeze)

`docker-compose.yml` frontend service has NO build section, so
`docker compose up --build` does NOT rebuild frontend source. The ONLY
authoritative frontend deploy is (from the canonical repo, at the exact
committed HEAD to deploy):

    docker build -f frontend/Dockerfile.deploy -t dive-analyser-frontend:latest frontend/
    docker compose up -d --force-recreate --no-deps frontend

then verify: live bundle `index-*.js/css` md5-identical to a fresh
canonical-tree `npm run build`, and deployed sourcemap first-party sources
byte-identical to Git. Never deploy from a dirty worktree or uncommitted
source. The maintained mirror (`mac-mirror`) is synced server-side;
server-to-mirror SSH uses `~/.ssh/divesensei_agent_key` via IdentitiesOnly
(U8 repair; already-authorized key, no new access).

## Test strategy

- `tsc --noEmit`, vitest unit/component suite, `npm run build`.
- Authenticated Playwright E2E (desktop chromium + mobile 390) against a
  local production preview (`vite preview`, `/api` proxied to live
  backend), reusing the stored real session (zero logins); read-only
  production smoke after deploy (bundle identity + route health + core
  API 4xx/5xx watch). Axe automation over Library/Viewer/Analysis/mobile.
