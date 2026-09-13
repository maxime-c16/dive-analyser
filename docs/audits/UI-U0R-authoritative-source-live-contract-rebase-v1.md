# UI-U0R — AUTHORITATIVE UI SOURCE AND LIVE CONTRACT REBASE V1

Date: 2026-09-13
Task: `UI-U0R — AUTHORITATIVE_UI_SOURCE_AND_LIVE_CONTRACT_REBASE_V1`
Worktree: `/home/mcauchy/dive-analyser-worktrees/ui-u0r-authoritative-rebase`
Branch: `ui-u0r-authoritative-rebase`
Initial canonical HEAD: `c4c9cfc1ad0ab77ccd9bea02d75f1a2c5b7560c5` (branch `uiux-overhaul-pro-app`)
Final canonical HEAD: see §Integration (this document commits in the worktree; final HEAD recorded in LOCAL_AGENT_REPORT).

> Evidence-note: all screenshots referenced below live in
> `docs/audits/evidence-ui-u0r-screenshots/` in this commit. Live inspection was
> performed with Playwright (Chromium desktop 1440×900, Chromium mobile-emulated
> 390×844) against the production app at `https://192.168.1.57:6443` (LAN).
> `shots/summary.json` / `shots/summary2.json` capture navigation state, video
> readiness and per-step observations.

---

## 1. Preflight / canonical state

- Canonical repo: `/home/mcauchy/dive-analyser` on `deb-serv`, branch `uiux-overhaul-pro-app`.
- Preflight canonical HEAD: `c4c9cfc1ad0ab77ccd9bea02d75f1a2c5b7560c5`
  (DIVE_ANALYZER_SUBJECT_RESOLUTION_AUDIT_V1, 2026-09-09).
  PROJECT_STATE (server working tree, updated 2026-09-13 by the infrastructure
  thread) still claims HEAD `e3c6cc4` — a commit dated 2026-09-09 that is an
  ancestor, not HEAD. **Documented disagreement:** fresh `git rev-parse` wins.
- Worktrees observed at preflight (concurrent workstreams):
  - main checkout (`uiux-overhaul-pro-app`, dirty with the infra thread's
    uncommitted session-auth + B2-playback-default work)
  - `subject-resolution-v1` (branch, at c4c9cfc)
  - `hurdle-identity-repair` (detached at ef1e55e)
  - `ui-u0r-authoritative-rebase` (created by this task)
- Remotes: `mac-mirror → divesensei@192.168.1.19:/Users/Shared/services/data/diveanalyzer-source-backups/dive-analyser-2026-09-05.git`.
  No `origin`.
- Mac-side mirrors (per PROJECT_STATE doctrine):
  - `~/.perso/diveanalyzer-perception.git` (bare mirror)
  - `~/.perso/diveanalyzer-perception` (working copy, was at `437b6af` = behind)
- Local Mac slice `~/.perso/diveanalyzer`: confirmed NOT a git repo, stale
  (PROJECT_STATE dated 2026-09-06, science-doc set already obsolete) — reference only.

### Concurrent workstreams observed (must not be broken)

1. **Infrastructure thread** (2026-09-12/13, UNCOMMITTED on main checkout):
   HTTPS migration, session auth (frontend `AuthContext.tsx`, `Login.tsx`,
   router guard, Dives/DiveVideoPlayer integration), B2 thumbnail fallback,
   DB connection-leak fix. Its frontend image was built 2026-09-12T13:03:55Z
   and is the currently deployed frontend. Only `docs/PROJECT_STATE.md` was
   touched on 2026-09-13 (11:58). No active edits observed during this audit.
2. Science workstreams (subject-resolution-v1 worktree, hurdle-identity-repair
   worktree): not touched by this task.

### Mechanical repair committed during this audit

- Commit `165eadfa4ce4aefcf5b070bdd780a8dca5b34e7a` on the canonical branch
  (made directly in the main checkout because the repaired files are the
  authoritative uncommitted working tree):
  - `frontend/src/test/setup.ts`: jsdom `IntersectionObserver` stub. jsdom
    lacks it; the Dives page's lazy-thumbnail effect crashed during both
    `Dives.test.tsx` tests, unmounting the tree (empty `<body>`).
  - Deleted 16 stray macOS AppleDouble `._*` junk files from `frontend/src`
    (untracked; one of them — `._DiveAnalysis.test.tsx` — broke vitest
    collection).
  - Post-repair validation: `tsc --noEmit` clean, `vitest run` 44/44,
    production build reproduces the deployed bundle hash byte-identically.
  No app-source or runtime behavior change. Committed separately so it stays
  identifiable.

---

## 2. DEPLOYED-SOURCE RECONCILIATION — P0 RESULT

**Classification: `AUTHORITATIVE_SOURCE_PROVEN_WITH_DOCUMENTED_BUILD_DRIFT`**

The drift is *Git-level* (deployed frontend source is uncommitted working
tree), not a wrong-source problem. The chain is proven end-to-end:

```
LIVE app https://192.168.1.57:6443
  → nginx reverse proxy container (repo nginx/conf.d, port 6090/6443)
  → container dive-analyser-frontend-1 (image dive-analyser-frontend:latest, built 2026-09-12T13:03:55Z)
  → image = nginx:1.27-alpine + /usr/share/nginx/html = vite production build of frontend/
  → build via frontend/Dockerfile.deploy (npm ci && npm run build → dist)
  → source = ~/dive-analyser/frontend/ working tree (UNCOMMITTED; includes the infra thread's session-auth work)
  → git: NOT in any commit (drift; commits 7ca1025/a2f7885 cover backend auth but the frontend files above are 'M'/untracked)
```

Proof chain (fresh, reproducible):

1. The deployed bundle ships a source map (`assets/index-BD0otN-g.js.map`,
   624 sources with `sourcesContent`). **All 44 first-party app sources in the
   deployed bundle are byte-identical (md5) to the current working tree**
   — including `pages/Dives.tsx`, `contexts/AuthContext.tsx`, `pages/Login.tsx`,
   `src/router.tsx`, `src/App.tsx`, `components/DiveVideoPlayer.tsx`.
2. A fresh production build of the current working tree
   (`rsync to /tmp/fbbuild → npm run build`) produced
   `index-BD0otN-g.js`, `index-nn85ibRJ.css` — **exactly the deployed asset
   hashes**. Repeated after the test-setup repair: identical.
   Container `index.html` md5 `af9682fe2a4bfb1fd6158e68541abc6` == fresh
   build `index.html`.
3. `frontend/dist` in the repo is a *stale older build* (`index-BUMgJG0X.js`,
   pre-auth) — it is **not** what is served and is gitignored. The prior
   task's warning "inspected frontend/src may be older than deployed" is
   resolved: the current working tree IS the deployed source.
4. Backend runtime (`dive-analyser-backend-1`) bind-mounts `./backend:/app`
   → backend runtime = same uncommitted working tree (auth.py, media.py,
   config.py, database.py, main.py modified uncommitted).

Build timestamps align: `pages/Login.tsx` mtime 2026-09-12 15:03:03 CEST;
image built 15:03:55 CEST; container created 15:04:11 CEST.

**Implication (must be fixed by U1/U2 or a dedicated commit):** the entire
current frontend (plus the auth backend) lives outside Git. Any redesign built
on the worktree-from-HEAD source would target the WRONG frontend. The
authoritative frontend tree is the main checkout working tree at
`~/dive-analyser/frontend` until the infra thread's work is committed.

---

## 3. Deployed runtime

| Item | Value |
|---|---|
| Environment | LAN app host `deb-serv` (192.168.1.57), Debian 12 |
| App URL | `https://192.168.1.57:6443` (HTTPS, self-signed) / `http://192.168.1.57:6090` |
| Deployment method | docker compose; nginx (6090/6443) → frontend container (6001:80) + backend (6002:8000) + postgres (127.0.0.1:5433) + adminer (8080) |
| Runtime identity | frontend image `dive-analyser-frontend:latest` built 2026-09-12T13:03:55Z, bundle `index-BD0otN-g.js`; backend container up 22h with `./backend` bind mount |
| Auth flags (live) | `USER_AUTH_ENABLED=true`, `B2_PLAYBACK_CANARY_ENABLED=true` (fail-closed production default per P6) |
| Source↔runtime match | frontend: PROVEN (§2). backend: bind-mount == working tree, source matches by construction |

---

## 4. CURRENT ROUTE MAP (authoritative source `frontend/src/router.tsx`, live-verified)

Global guard: all routes except `/login` wrapped in `AuthGuard` (session check
via `/api/v1/auth/me`; unauthenticated → `/login?state.from=path`). Layout:
desktop left sidebar (`lg:`) + mobile top bar with slide-in drawer; breadcrumbs
for all authed routes. Login renders bare (no sidebar).

| URL | Route component | Nav label | Reachability | Live check | Notes |
|---|---|---|---|---|---|
| `/` | `pages/Dashboard.tsx` | Overview | Global nav (first) | OK — "Training Dashboard" KPI page | Root default. `Total dives 2129 / Success rate 72.6% / Avg perf 4.80 / Avg DD 1.6 / Max DD 2.4 / Sessions 162` + DD rulebook panel + monthly charts + recent progress |
| `/dashboard` | `<Navigate to="/" replace>` | — | Redirect | OK → `/` | redirect only |
| `/journey` | `pages/Journey.tsx` | Journey | Global nav | OK | narrative + timeline + milestones + psychology |
| `/analytics` | `pages/Analytics.tsx` | Analytics | Global nav | OK — "Detailed Analytics" | monthly/by-height/by-direction/trending charts |
| `/dives` | `pages/Dives.tsx` | Dives | Global nav | OK — "Browse attempts" library | see §8 |
| `/dives/analysis/:diveCode` | `pages/DiveAnalysis.tsx` | none (contextual) | Contextual only (reader "Analyze {code}" link) | OK — "103B Per-dive intelligence"; 186 attempts/41 sessions/134 cached clips | deep per-dive-code analysis workspace w/ filters, weighting, period comparison, personal-dive-value panel, representatives |
| `/media/representatives` | `pages/RepresentativeMedia.tsx` | Representatives | Global nav | OK — "Representative Media" | per-dive-code gallery of representative clips; replacement/prepare tooling |
| `/media/recall` | `pages/MediaRecall.tsx` | Media recall | Global nav | OK — "Media recall" | operational media-tooling console (agents, catalog runs, recall batches) |
| `/media/p5-canary` | `pages/P5Canary.tsx` | **Player** (!) | Global nav | OK — stuck on "Checking session…" | P5 auth/B2 playback canary harness page; self-managed login flow; duplicate Film icon + misleading label |
| `/admin` | `pages/Admin.tsx` | System | Global nav | OK — operations status panel | read-only ops status (operationsApi) |
| `/sessions` | `pages/Sessions.tsx` | Sessions | Global nav | OK — "Training Sessions" | session list + SessionDetail (own player/details) |
| `/competitions` | `pages/Journey.tsx` (alias) | Competitions | Global nav | OK — renders Journey | alias route, no unique content |
| `/login` | `pages/Login.tsx` | — | Outside layout | OK | email+password+remember-30d; error on failure |
| no match | — | — | — | `/nonexistent-route-xyz` renders nav + breadcrumbs + EMPTY content | **no 404/fallback route** (inner Routes render null) |

Observed live counts: Overview KPI "2129 personal attempts"; Dives default
scope=self 2188 attempts; with `q=103` scope=self 444; scope=all incl.
training partners.

Screenshots: `d02-dashboard`, `d03-dives-default`, `d12-journey`, `d18-analytics`,
`d19-sessions`, `d20-representatives`, `d21-media-recall`, `d22-p5canary`,
`d23-admin`, `d24-competitions`, `d25-dashboard-redirect`, `d26-fallback-404`,
`d28-diveanalysis`.

---

## 5. GLOBAL NAVIGATION INVENTORY

**Desktop (`≥lg`):** permanent left sidebar, 10 items, single flat list,
ordered: Overview, Journey, Analytics, Dives, Representatives, Media recall,
Player, System, Sessions, Competitions. Active item boxed (border + panel
background). No account menu (no logout affordance in shell — logout exists
only inside the P5Canary page). No route-specific sub-navigation; per-page
controls (filters, view switchers) live inside page content.

**Mobile (`<lg`):** sticky top bar (brand + current-route label + hamburger);
full-screen slide-in drawer with the same 10 items; closes on Escape and on
navigation; touch targets ≥44px (`touch-target` class). No bottom tab bar.

**Breadcrumbs:** `Dive Analyser / {route}` derived from URL segments, desktop
only (`sm:flex`), decorative for deep paths (e.g. `/dives/analysis/103B`
shows an unusable "Analysis" crumb).

**Contextual navigation:** within the Dives reader: Previous/Next buttons
(over the *current filtered result set*), "Analyze {code}" link to
`/dives/analysis/:code`, reader Close (X + Escape + backdrop click). Mobile
nav drawer. No Previous/Next on DiveAnalysis (its own list navigation exists
for attempts within the analysis view).

Provisional classification of nav destinations:
CORE = Dives; SECONDARY = Sessions, DiveAnalysis, Representatives, Analytics;
OPERATIONAL = Media recall, System(admin), Player(p5-canary);
LIKELY_DUPLICATE = Competitions (alias of Journey), Overview (dashboard
content overlaps Analytics + Sessions + Dives recent-row); UNKNOWN = Journey.

---

## 6. COMPONENT OWNERSHIP MAP

| Concern | Owner (authoritative tree) | Status |
|---|---|---|
| App shell | `src/App.tsx` → AuthProvider + SyncStatusProvider + BrowserRouter + SyncNotifications/MilestoneNotifier/SyncErrorHandler globals | active |
| Router + global nav + breadcrumbs + mobile drawer + Layout | `src/router.tsx` | active |
| Auth | `src/contexts/AuthContext.tsx`, `src/pages/Login.tsx`, backend `auth.py` (uncommitted infra work) | active |
| Library (Dives) | `src/pages/Dives.tsx` (944 lines: search parser, filters, grid/list, AttemptCard/AttemptRow, DiveThumbnail, AttemptReader modal w/ Previous/Next, preview cache) | active; `Dives.test.tsx` covers it |
| Clip player (shared) | `src/components/DiveVideoPlayer.tsx` (262 lines) | active, used by Dives reader + DiveAnalysis |
| Canary player page | `src/pages/P5Canary.tsx` | operational harness; labeled "Player" in nav |
| Dive analysis | `src/pages/DiveAnalysis.tsx` + `services/diveAnalysisApi.ts`, `components/PersonalDiveValuePanel`, `getRepresentatives` | active |
| Sessions | `src/pages/Sessions.tsx` + `components/SessionDetail.tsx` (+ SessionDirectionIndicator) — SessionDetail has its own playback path | active |
| Overview/Dashboard | `src/pages/Dashboard.tsx` (796 lines) + `components/RecentProgress`, `DDProgressionChart`(9-line stub), `AvoidedDives`, `MentalBlockIndicator`, `PersonalDiveValuePanel` | active; old-style palette |
| Journey | `src/pages/Journey.tsx` + `components/JourneyNarrative`, `JourneyTimeline`, `JourneyWithSync`, `DiveStory`, `EmotionalStateCapture`, `MilestoneNotifier`, `MentalBlockIndicator` | active; `/competitions` aliases it |
| Analytics | `src/pages/Analytics.tsx` + recharts | active |
| Representatives | `src/pages/RepresentativeMedia.tsx` + `services/representativeMediaApi.ts` | active |
| Media recall | `src/pages/MediaRecall.tsx` + `services/mediaRecallApi.ts` | active, operational |
| Admin/System | `src/pages/Admin.tsx` + `services/operationsApi.ts` | active |
| Sync plumbing | `contexts/SyncStatusContext.tsx`, `hooks/useSyncStatus.ts`, `components/SyncStatus/SyncNotifications/SyncErrorHandler` | active |
| API layer | `services/api.ts` (axios, relative `/api`); media: `services/mediaApi.ts` (fetch, session-credentials implicit same-origin) | active |
| State helpers | `hooks/usePreservedSearchParams.ts` (replace-mode URL param writes) | active |
| Design tokens | `src/index.css` (`--app-*` custom properties + `@layer utilities` app-* classes, `.touch-target`, `.app-input`, `.mobile-scroll-region`, ops animations) | active |
| Legacy visual system | old Tailwind palette (gray/cyan) hard-coded in Dashboard, Journey, Analytics, Sessions + 12 components | legacy, still rendered on 4 major routes |
| Loading/error primitives | none shared — every page hand-rolls spinner/error/empty blocks | gap |

Dead/uncertain: none found in `frontend/src` (every page is routed); the
repo-level `Dockerfile` (dev-server variant) is dead deployment config —
superseded by `Dockerfile.deploy` (bundled image runs nginx).

---

## 7. CURRENT LIBRARY / DIVE-BROWSER CONTRACT (`/dives`)

Data source: `GET /api/v1/dives?limit=5000&exclude_lineup=true&diver_scope=all`
+ `GET /api/v1/divers`, fetched once on mount; all filtering/search is
client-side over the full array. Backend order: `dive_datetime DESC, id DESC`
(`backend/app/api/v1/dives.py:85`).

Controls and where their state lives:

| Control | State location |
|---|---|
| Search query `q` (structured parser: code/height/SYNC/INDIVIDUAL/modifiers/rating/position words + free text) | URL search param (replace-mode) |
| Athlete scope `scope` (`self` default / `all`) | URL param; filtering by `diver.is_primary_user` client-side |
| Height, Context (sync/individual), Rating, Modifiers | URL params |
| View mode `view` (grid/list) | URL param |
| Pagination `shown` (48 + "Show 48 more", client slice) | component state (resets on any filter change) |
| Selected clip (reader open) | component state — **not in URL** |
| Scroll position | browser default (body overflow locked while reader open) |
| Result counts (attempts/codes/avg) | derived, header chips |

Features present: search, filters, scope, grid/list, Recent attempts
horizontal scroller (first 10), lazy IntersectionObserver thumbnails
(B2 poster or `<video preload=metadata>` first-frame fallback with cached
proxy URL), media status badges (Ready/Linked), score badge, reader dialog
with player + detail sidebar + Previous/Next + Analyze link.

NOT present: sorting controls (fixed recency order), favorites, ratings
beyond caption performance, collections, session grouping/sectioning,
save/share of a clip URL, deep-linkable open clip state.

---

## 8. LIBRARY-STATE PERSISTENCE TEST (live, non-destructive)

Scenario A: `Library(/dives?q=103&view=list) → /journey → browser Back`:

| State | Result |
|---|---|
| search | **PRESERVED** (URL param; input shows `103`) |
| view mode | **PRESERVED** (`view=list` re-applied) |
| scope/filters | **PRESERVED** (URL params) |
| scroll | **LOST** (browser restores approximate scroll on same-entry back only; here reset) |
| selected clip | n/a (was closed) |

Scenario B: reader open → browser Back: dialog does NOT intercept history →
`goBack()` left `/dives?q=103` entirely and landed on `/` (previous history
entry = post-login redirect). Reader/selected-clip is **LOST** on browser back;
user is dumped to Overview, not the library. App-internal close (Escape/X)
preserves filters (URL unchanged) — **PRESERVED** for filters via URL.

Scenario C: hard reload of `/dives?q=103`: search **PRESERVED** (URL param).

| State | Reload | Back-from-other-route | Reader open→close | Verdict |
|---|---|---|---|---|
| search | PRESERVED | PRESERVED | PRESERVED | URL-backed |
| scope/filters/sort/view | PRESERVED | PRESERVED | PRESERVED | URL-backed |
| pagination depth | LOST (resets to 48) | LOST | n/a | component state |
| scroll position | LOST | LOST | restored-ish after close (browser) | PARTIAL |
| selected clip | LOST (no URL state) | LOST | n/a | LOST |
| browser Back from clip | — | leaves app route (loses Library entirely) | — | BROKEN UX |

Previous/Next ordering: over the **current filtered result set**, in backend
default order (`dive_datetime DESC, id DESC`). Evidence: reader on `q=103`
showed "Selected attempt · 1 of 444" and index tracked 1→2→3→2→1 with
Previous/Next buttons correctly disabled at the boundaries. All top results
were `103B · 22 Aug 2026 · 13:03` — that is a sync pair (two divers, same
timestamp) — matches data model, not a bug.

Counting discrepancy (minor defect): header says "443 attempts", reader
says "1 of 444" — off-by-one from `useDeferredValue` timing during measurement
(re-run showed stable 443/443 in the header vs 444 during typing transition).
Record as cosmetic; verify during U1.

---

## 9. CURRENT PLAYBACK PATH (end-to-end, proven with clip 5124D + 103B)

```
clip record (dives.video_uuid) — user opens card in /dives grid
 → reader dialog mounts <DiveVideoPlayer diveCode height videoUuid>
 → GET /api/v1/media/{video_uuid}/status  (backend app/api/v1/media.py::_status_for_asset)
     status ∈ {ready, queued, waiting_for_mac, claimed, exporting, transcoding,
               uploading, verifying, failed, unavailable, ...}
     returns playback_url, poster_url, can_request, available_renditions, job{last_error}
 → playback_url resolution (backend):
     1) B2 backbone: latest verified PROD MediaRevision joined to verified prod
        MediaBlobLocation → /api/v1/media/revisions/{id}/play
        (media_playback.py: auth-checked, HEAD-proofs B2 at grant time, presigns
         GET TTL=MEDIA_PLAYBACK_PRESIGN_TTL_SECONDS(120, clamp 1–300), 302 redirect;
         presign failure → authenticated legacy stream fallback; owner-binding
         enforced via can_user_access_media)
     2) else legacy cache: /api/v1/media/cache/{entry_id}/play (Range-capable
        authenticated stream of media/cache proxy)
 → browser native <video controls playsinline preload=metadata poster=...>
 → states: queued..verifying → poll every 3s; failed/unavailable → error + 
   "Retry prepare" if can_request; not cached & can_request → "Prepare clip"
   (POST /api/v1/media/{uuid}/request {rendition:'proxy_360p', reason:'user_view'})
```

Live-verified variants:
- Local-cache-backed clip (5124D): status `ready`, playback
  `/api/v1/media/cache/2265/play`, poster present, renditions
  `[poster, proxy_360p, proxy_720p]` — video element loaded
  (readyState 4, duration 16.77s) both desktop and mobile.
- B2-backed clip (103B): status `ready`, playback
  `/api/v1/media/revisions/{1717|2204}/play` (B2 presign proxy), no poster,
  `available_renditions: []` — loads fine in reader; grid thumbnail falls
  back to `<video preload=metadata>` first-frame trick.
- Not-ready clip (5211A, "Linked" badge, 49 such cards on default view):
  reader opens normally with player area; no dead end.
- Thumbnails: per-card `GET /api/v1/media/{uuid}/status` gated by
  IntersectionObserver (rootMargin 200px) with in-process cache — previously
  2000+ concurrent status calls exhausted the DB pool; now bounded.

Legacy vs current: legacy `media/videos` streaming still exists for cache
entries; B2 backbone path is primary when `B2_PLAYBACK_CANARY_ENABLED`.
P5Canary page is a separate debug harness (not used by core UI).

---

## 10. ASYNC / LOADING / FAILURE-STATE AUDIT (current → future taxonomy)

| Surface | Loading | Empty | Error | Future-state fit | Gaps |
|---|---|---|---|---|---|
| `/dives` list | "Loading your dive library…" text block | "No attempts match this search." (search-empty only; no-data-vs-error distinguished) | red banner, **no retry button** (reload required) | RETRYABLE_ERROR gap | single fetch-all (5000) — no incremental loading; failure leaves empty page w/ banner |
| Thumbnail | silent (placeholder dive-code tile) | placeholder | placeholder (silent) | STALE_OR_CACHED ok | failed status request cached as "no media" — never retried in-session |
| Player | spinner + "Preparing media: {state}" while polling 3s | n/a | error panel; "Retry prepare" when can_request | READY/RETRYABLE mostly ok | poll errors only console.debug → **indefinite spinner possible** if status endpoint keeps failing while status is a prep-state; video element decode errors show generic "Video could not be loaded" without retry |
| Sessions | page-level loading text | empty list | console only?? (grep shows no error UI in page top) | gap | silent failure risk |
| Dashboard | loading text | partial | error text | gap | 5 parallel endpoints; no retry |
| Journey/Analytics | same pattern | same | same | gap | same |
| Representatives/MediaRecall/Admin | hand-rolled | hand-rolled | hand-rolled | operational; lower priority | inconsistent |
| Login | busy state | n/a | inline error | good | — |
| AuthGuard | "Loading…" | n/a | redirects to /login | good | session expiry mid-action → player shows "Sign in to play" overlay (good) |

No infinite-spinner found in the primary path during live tests; the
theoretical indefinite spinner is the player poll loop when `getMediaStatus`
throws repeatedly (status stays stale, spinner persists).

---

## 11. DESKTOP BASELINE FINDINGS

Workflow `open → find known clip → play → next → back`:

- Top-level nav choices: **10** (Overview, Journey, Analytics, Dives,
  Representatives, Media recall, Player, System, Sessions, Competitions) —
  3–4× the core task needs.
- Find clip: `/dives` search box is first-class, structured parser documented
  inline ("Try 103, 103B, 103 Pike, or 103B DB"); filters compact; counts
  chips (Attempts/Codes/Average).
- Open clip: click card → right-side reader dialog, player prominent,
  details sidebar, Previous/Next, Analyze link. **No URL change** (state
  lost on back/refresh; not shareable).
- Play: native controls; playback via B2 presign or local cache; loads in
  ~1s for local, B2 302→206 verified previously by P6 and confirmed loading
  here (readyState 4).
- Next/Previous: works over filtered set; title updates; boundaries disable.
- Back: application has no global back; browser Back exits the Library to
  the previous history entry (does NOT close the reader) — the "exact
  Library state restored" contract is only met for URL-param filters.
- Dashboard prominence: root page is a KPI dashboard (Total Dives, Success
  Rate, Avg Performance, DD panels, monthly charts) — far from the clip-first
  direction; duplicated "recent attempts" concept also lives in Dashboard
  (RecentProgress) and Dives (Recent attempts scroller).
- Player page ("Player" nav item = P5Canary) is a dev harness stuck at
  "Checking session…" — appears broken in nav context and duplicates a label
  already implied by the library reader.
- Friction list: 10-item nav with two "Player"-family items; Overview
  competes with Library as home; reader not deep-linkable; Competitions is
  an empty alias of Journey; Sessions duplicates browse+play with its own
  player/detail path (SessionDetail) that diverges from DiveVideoPlayer.

Evidence: `d02`, `d03`, `d04`, `d05`, `d06`, `d07–d09`, `d10–d14`, `d15`, `d16`,
`d22`, `d28`.

---

## 12. MOBILE BASELINE FINDINGS (390×844, tested, not inferred)

- Nav: hamburger + drawer (10 items, full-screen). Drawer closes on
  navigation. No horizontal overflow detected
  (`scrollWidth - clientWidth = 0`).
- Library: filter grid compresses to 2 columns; selects full-width; scroller
  "Recent attempts" swipeable; list rows adapt (date under code, chevron);
  touch targets respect `.touch-target` (44px).
- Reader: full-width sheet; player ~16:9 with poster; Previous/Next large
  buttons; details below player (scroll); metadata density fine.
- Player: native controls, `playsInline`; playback loads (readyState 4,
  duration known) — mobile playback works through B2 proxy path.
- Sticky elements: mobile top bar only; reader header sticky.
- Charts/dashboard compression: not tested via a mobile Journey/Analytics
  deep pass beyond load; route screenshots show recharts reflow but a
  dedicated U4 pass should verify.
- Back behavior on mobile: same as desktop (browser back leaves Library;
  drawer Escape works). Touch-target sizing good; no obvious horizontal
  overflow or compression defects in the core loop.

Evidence: `m-01`–`m-07`.

---

## 13. KEYBOARD / ACCESSIBILITY BASELINE (bounded, core workflow)

- Tab order (freshly loaded /dives): 10 sidebar links → "Dive Analyser"
  breadcrumb → "My dives" scope button → search input → selects → modifier
  buttons → reset → cards. Logical, no traps observed.
- Focus visibility: global `button:focus{outline:3px solid var(--app-accent)}`
  + `focus-visible` outline on cards/rows; NavLink focus styles present.
- Enter/Space: cards and rows are `<button>`s (Enter/Space activate);
  reader close/previous/next are buttons.
- Player controls: native `<video controls>` → space/arrows work once
  focus reaches the video; no custom seek/fullscreen needed.
- Reader Escape: closes (verified). Arrow keys do NOT navigate
  Previous/Next (`reader_arrowkeys_change_title = false`) — gap.
- Reader dialog: `role=dialog`, `aria-modal`, labelled title; focus is NOT
  trapped (Tab can escape into background) — gap for U4/U5.
- Semantic labels: aria-labels on nav toggle, search, view toggles, cards
  ("Open 103B attempt from …"), close button. Breadcrumbs `hidden` on mobile.
- Touch targets: `.touch-target` enforces ≥44px.
- Color-only states: media readiness uses text badge + dot (color + text) — OK.
- 200% zoom sanity (720×900 viewport check): layout stacks, no horizontal
  overflow (`d27`).
- Reduced motion: ops animations gated by
  `prefers-reduced-motion: no-preference`; spinner animation not gated — minor.
- Major gaps (for U4/U5): no focus trap in reader; no ArrowLeft/Right
  paging; grid thumbnails `<video preload=metadata>` are decorative-but-
  focusable-ish inside buttons (fine); no skip-to-content link; login
  error announced as plain text (no aria-live).

---

## 14. VISUAL-SYSTEM / STYLE OWNERSHIP AUDIT

Architecture: **Tailwind (v3-era, utility classes in JSX) + a hand-rolled
token layer**: `src/index.css` defines `--app-bg/panel/panel-elevated/border/
border-strong/text/muted/accent` and maps them to Tailwind utilities
(`.bg-app`, `.text-app-muted`, etc.) via `@layer utilities`. `App.css` (34
lines) + `styles/sync.css` (196 lines) hold legacy/global bits. No
CSS-in-JS, no component library (lucide-react for icons only, recharts for
charts), no theme provider, no design-token file beyond index.css.

Two competing palettes coexist:

1. **Token system (new)** — router/nav, Dives, DiveAnalysis,
   RepresentativeMedia, MediaRecall, Admin, P5Canary, Login use `app-*`.
2. **Legacy hard-coded palette (old)** — Dashboard (11), Journey (46),
   Analytics (14), Sessions (21) pages + 12 components
   (SessionDetail 44, DiveStory 36, RecentProgress 27, AvoidedDives 30,
   SyncStatus 20, DiveVideoPlayer 12…) use raw `bg-gray-…/text-cyan-…`.
   `DiveVideoPlayer` itself (the shared player) still ships the old
   gray/cyan error/prepare overlays — visible inconsistency inside the
   new reader chrome.

Ownership to consolidate for U1/U2: colors/typography/focus → `index.css`
tokens; spacing/radii → ad-hoc Tailwind classes (no token scale);
status colors → per-component (`performanceClass` map in Dives.tsx);
responsive breakpoints → default Tailwind (`sm/lg/xl/2xl`).

---

## 15. ROUTE OVERLAP / DUPLICATION ANALYSIS

Question applied: "Does this screen help the user find, watch, understand,
or move between dive clips?"

| Route | Verdict | Reason |
|---|---|---|
| `/` Overview | AGGREGATE_SECONDARY | KPI dashboard; overlaps Analytics (stats), Dives (recent attempts), Sessions (counts). No clip browsing/playback of its own. |
| `/journey` | AGGREGATE_SECONDARY (narrative/psychology) | unique narrative/milestone content; no browsing |
| `/analytics` | AGGREGATE_SECONDARY | pure charts; overlaps Dashboard panels |
| `/dives` | **UNIQUE_CAPABILITY — the Library** | the only surface with search+filter+all clips+reader+Prev/Next |
| `/dives/analysis/:code` | UNIQUE_CAPABILITY (analysis) | per-dive-code deep stats; contextual from reader |
| `/media/representatives` | PARTIAL — DUPLICATES_CLIP discovery (gallery of per-dive-code reps with own player cards) + operational replacement tooling | |
| `/media/recall` | OPERATIONAL_ONLY | media console |
| `/media/p5-canary` | OPERATIONAL_ONLY + UI DEBT | auth/playback canary harness; mislabeled "Player"; stuck "Checking session…" in nav context |
| `/admin` | OPERATIONAL_ONLY | ops status |
| `/sessions` | DUPLICATES_LIBRARY + DUPLICATES_CLIP (own browse→detail→player path via SessionDetail) | session-centric grouping could fold into Library grouping/filter |
| `/competitions` | DUPLICATE (renders Journey; zero unique content) | |
| `/login` | KEEP (auth, out of scope) | |

---

## 16. TESTS / BUILD BASELINE

| Check | Command (discovered from `frontend/package.json`) | Result |
|---|---|---|
| typecheck | `npm run typecheck` (tsc --noEmit) | PASS (exit 0) |
| lint | `npm run lint` (eslint flat-config migration pending) | **NOT_CONFIGURED in practice** — eslint 9 rejects legacy invocation; not part of working CI; documented |
| unit/component | `npx vitest run` | **44/44 PASS** (after mechanical repair §1) |
| production build | `npm run build` (tsc && vite build) | PASS; reproduces deployed bundle byte-identically |
| e2e/browser | `npx playwright test` (baseURL = live app) | **34/34 FAIL — pre-existing**: suite predates session auth (asserts unauthenticated DOM); needs an auth fixture. Pre-existing, non-blocking for U0R; REQUIRED repair before U1/U2 relies on it |
| backend tests | not run (out of frontend scope; science threads own backend validation) | NOT_RUN |

---

## 17. KNOWN DEFECTS (observed)

1. Frontend+auth backend source uncommitted (biggest durability gap; documented drift).
2. No 404/fallback route — unknown URLs render nav with empty content.
3. Reader/selected-clip state not URL-backed: not shareable, not back-safe,
   lost on reload; browser Back from an open reader exits the Library.
4. "Player" nav item is the P5Canary harness (stuck "Checking session…",
   duplicate icon/label with Representatives).
5. `/competitions` silently renders Journey.
6. Count off-by-one risk (header vs reader "N of M") under deferred query.
7. `/dives` load failure has no retry affordance; distinct empty vs error state.
8. Player poll can spin indefinitely if status endpoint errors persist.
9. Two visual systems (token vs legacy gray/cyan); DiveVideoPlayer overlays
   visually diverge from the reader chrome.
10. e2e suite completely broken by auth (no fixture).
11. Breadcrumbs generate meaningless intermediate crumbs (e.g. "Analysis").
12. No logout/account control in the main shell (only inside P5Canary).

---

## 18. IMPLEMENTATION IMPLICATIONS FOR U1/U2 (evidence → design)

1. **Dives.tsx IS the natural Library base** — it already implements
   URL-param filter state, structured search, grid/list, lazy media badges,
   and a reader with Prev/Next over the result set. It was clearly
   redesigned recently in the clip-first direction ("Browse attempts",
   "Dive library").
2. Missing for the V1 contract: (a) reader state in URL
   (`?clip=<video_uuid>` or `/dives/:id`) so Back closes the reader and
   restores exact Library state; (b) scroll restoration; (c) retry affordance
   on list error; (d) empty-state separation. All frontend-only; no backend
   redesign needed for Prev/Next (already client-side over the result set).
3. Home decision (supervisor): make `/` = Library (redirect `/`→`/dives` or
   re-point root) or keep a slim Overview. Dashboard content overlaps both
   Analytics and Sessions; U1 can route `/`→Library without data loss.
4. Consolidation targets: Sessions (merge browse into Library as
   session-grouping/filter; keep SessionDetail analysis only if needed),
   Competitions (alias — remove), Player/P5Canary (rename or unhook from
   nav), Representatives (secondary, keep reachable), MediaRecall/Admin
   (operational, keep but demote), Overview (merge → Analytics or slim).
5. Shared player: DiveVideoPlayer is the single core player; SessionDetail
   has its own player path to fold in later.
6. Auth context (new) is already consumed by router + player; U1 must keep
   `AuthGuard` + `/login` semantics untouched (infra thread's contract).
7. Mobile is one coherent component system (same router/Layout/tokens) —
   U1 can build mobile-first against Dives/DiveAnalysis/Reader only.

---

## 19. RECOMMENDED NEXT GATE

Authorize `UI-U1/U2 — MINIMAL_IA_AND_LIBRARY_CORE_V1` with scope:

- Nav: reduce to Library (+ contextual Analysis) + secondary (Sessions,
  Representatives, Analytics, Journey) + operational (Media recall, System)
  + login/logout account affordance; fix "Player" label; drop Competitions
  alias; root `/` decision (Library as home recommended).
- Reader deep-link (URL state) + scroll/pagination restoration on Back.
- Error/empty taxonomy on `/dives` (READY/EMPTY/RETRYABLE_ERROR/STALE).
- Keep all existing routes reachable during migration (no removals in U1/U2).
- Prerequisite repair items to fold in: 404 route; e2e auth fixture;
  commit the uncommitted frontend/auth working tree (or coordinate the
  infra thread to commit first).

Preconditions confirmed: authoritative source proven (§2); playback path
proven; Library state model mapped; validation baseline green (except e2e,
documented).
