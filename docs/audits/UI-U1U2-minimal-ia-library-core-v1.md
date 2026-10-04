# UI-U1/U2 — MINIMAL IA AND LIBRARY CORE V1

Date: 2026-09-13
Task: `UI-U1/U2 — MINIMAL_IA_AND_LIBRARY_CORE_V1`
Worktree: `/home/mcauchy/dive-analyser-worktrees/ui-u1u2-library-core-v1`
Branch: `ui-u1u2-library-core-v1`
Initial canonical HEAD: `defc6cfae5f36c6e3b4f7a56dfa569efd157db35` (branch `uiux-overhaul-pro-app`, identical to U0R final)
Final canonical HEAD (this gate): `75fca591ebf0323edf4d403a914cd19ca6c4c028`
(merge of `ui-u1u2-library-core-v1` into canonical). Canonical has since
advanced with concurrent science merges (`f00dffd7...` Subject Resolution Cohort
Expansion V1) that preserve this gate's frontend content byte-for-byte.

> Evidence: `docs/audits/evidence-ui-u1u2-screenshots/` (14 captures: d01–d08
> desktop 1440×900, m01–m04 mobile 390×844, s01–s02 reliability states).
> All live inspection ran against the NEW build served by a local production
> preview (`vite preview` on :4173, API proxied to the live backend) before
> deployment, and the final E2E suite was also run against that preview.
> Live post-deployment smoke results are in §13.

---

## 1. Preflight / fresh authority

- Canonical repo `/home/mcauchy/dive-analyser`, branch `uiux-overhaul-pro-app`,
  HEAD `defc6cf` (unchanged since U0R). Read: `docs/PROJECT_STATE.md` (server
  working tree, infra thread's 2026-09-13 update + U0R section) and
  `docs/audits/UI-U0R-authoritative-source-live-contract-rebase-v1.md`.
- Worktrees at preflight: main checkout (dirty), `subject-resolution-v1`,
  `hurdle-identity-repair` (detached), `ui-u0r-authoritative-rebase`.
- Deployed bundle identity: `index-BD0otN-g.js` (image
  `dive-analyser-frontend:latest` built 2026-09-12T13:03:55Z) — unchanged since
  U0R. Deployed↔working-tree identity re-verified fresh: the deployed
  sourcemap's first-party sources (153) md5-match the working tree for every
  overlapping file (`App.tsx`, `router.tsx`, `Dives.tsx`,
  `DiveVideoPlayer.tsx`, `AuthContext.tsx`, `Login.tsx`,
  `usePreservedSearchParams.ts`).
- No file under `frontend/src`, `backend/app`, `docs` was modified after
  13:34 on 2026-09-13 (post-U0R-merge) → no active edits anywhere.

## 2. Concurrent ownership resolution (P0 gate)

State found: the infra/auth/frontend work was still **uncommitted** in the main
checkout (case between B and C of the packet trichotomy), but fresh evidence
shows it is **complete and dormant, not active**:

- The infra thread's own PROJECT_STATE declares every item COMPLETE
  (session auth, HTTPS migration, B2 thumbnail fallback, remember-me) and
  states "Infrastructure is in a stable, fully operational state."
- The work is the **deployed, live** source (proven in U0R §2 and re-verified
  in this preflight) — it cannot be abandoned or reverted.
- Zero file modifications since 2026-09-12 15:03 (frontend source) /
  2026-09-13 11:58 (docs only); U0R observed no active edits; none since.

Resolution: the required handoff/commit was performed as a **path-limited
attribution commit made directly in the main checkout** (the only place the
uncommitted content exists), committing exactly the infra thread's files:

```
0133386c7bc0b1f5fe6408f105868c1f875db1fb
"Infrastructure thread handoff: durable commit of completed, deployed
session-auth/HTTPS/B2-thumbnail work ..."
13 files, +456/−78
```

- Committed: `backend/app/{api/v1/auth.py,api/v1/media.py,config.py,database.py,main.py}`,
  `frontend/src/{App.tsx,router.tsx,pages/Dives.tsx,components/DiveVideoPlayer.tsx}`,
  `frontend/src/contexts/AuthContext.tsx` (new), `frontend/src/pages/Login.tsx` (new),
  `nginx/conf.d/default.conf`, `ops/postgres-backup.sh` (mode only).
- **Not touched:** the science thread's staged deletions
  (`docs/science/DIVE_ANALYZER_SUBJECT_RESOLUTION_*`,
  `experiments/subject_resolution/*`) and untracked science experiments
  (`experiments/landmark_pilot/*`, annotation frames) — verified still
  staged/untracked after the commit.
- Content safety: md5 of all 12 committed files recorded pre-commit and
  verified identical post-commit; deployed-bundle identity unaffected
  (commit does not change content).
- No overwrite/reset/stash/cherry-pick/index surgery was used.

## 3. Dedicated worktree

```
path:      /home/mcauchy/dive-analyser-worktrees/ui-u1u2-library-core-v1
branch:    ui-u1u2-library-core-v1
base_head: 0133386c7bc0b1f5fe6408f105868c1f875db1fb
```

Clean base containing the authoritative source for the first time (the U0R-era
worktree-from-HEAD problem is resolved: the worktree now contains the real
deployed frontend).

## 4. Routes before → after

| Route | Before | After |
|---|---|---|
| `/` | Dashboard (product home) | **redirect → `/dives`** (query preserved) |
| `/dashboard` | redirect → `/` | **Dashboard renders here** (secondary Overview) |
| `/dives` | Library ("Browse attempts") | Library (canonical, unchanged URL) |
| `/dives/analysis/:diveCode` | contextual analysis | unchanged |
| `/journey`, `/analytics` | nav | unchanged, secondary nav |
| `/media/representatives` | nav | unchanged, secondary nav |
| `/media/recall` | nav | unchanged, **Operations disclosure** |
| `/media/p5-canary` | nav ("Player") | **hidden from nav**, route reachable |
| `/admin` | nav ("System") | **Operations disclosure**, route reachable |
| `/sessions` | nav | unchanged, secondary nav |
| `/competitions` | nav (Journey alias) | **hidden from nav**, route reachable (removal deferred to U6) |
| `/login` | bare login | unchanged |
| no match | nav + empty content | **NotFound page: "Page not found" + "Back to Library"** |

## 5. Navigation before → after

Before: single flat 10-item list (Overview, Journey, Analytics, Dives,
Representatives, Media recall, Player, System, Sessions, Competitions) in the
desktop sidebar and the mobile drawer.

After:

- **PRIMARY:** Library (`/dives`) — visually emphasized (larger, semibold).
- **SECONDARY** (grouped under a "Review" label, smaller/muted):
  Overview (`/dashboard`), Journey, Analytics, Representatives, Sessions.
- **OPERATIONS** (collapsed disclosure, closed by default, `aria-expanded`
  controlled): Media recall, System (`/admin`).
- **Hidden from normal nav:** Player canary (`/media/p5-canary`),
  Competitions (`/competitions`).
- Sidebar description rewritten to orient on the Library ("Your clips live in
  the Library…"). Mobile drawer mirrors the same hierarchy with the same
  disclosure; the mobile top-bar brand now links directly to `/dives`.
- No logout/account affordance was added (AuthContext change would touch the
  infra thread's auth surface; deferred — see Remaining debt).

## 6. Library information hierarchy (first screen)

- Header: eyebrow "Dive library", H1 **"Library"**, one functional help line.
- Count chips reduced to **Attempts** and **Codes**; the "Average" analytics
  chip was removed (first-screen competition per packet §13).
- The **"Recent attempts" horizontal strip was removed** — it duplicated the
  first 10 items of the filtered result set directly below it (pure
  presentation duplication, no capability loss; the grid/list remain).
- Scope toggle (My dives / Everyone), structured search, and the compact
  filter row (Height, Context, Rating, Modifiers, Reset) are unchanged and
  fully visible — no filter capability was removed or demoted (they were
  already the highest-signal set).
- Cards/rows unchanged (already within the §14 information budget:
  poster/first-frame, code, date, height/platform/phases/modifiers, score).
- All styling uses the existing `--app-*` token system / `app-*` utilities;
  no third visual system introduced.

## 7. Selected-clip URL contract

- Parameter: **`clip`** on `/dives` (e.g. `/dives?q=103&view=list&clip=12431`).
- Identity: **the attempt's stable DB id** (`dives.id`) — deliberately not the
  media UUID, so attempts without playable media are addressable too.
- Open (card click): **PUSH** one history entry `Library URL + clip`.
- The reader is **derived state**: `selected = filtered.find(id === clip)`.
  It is no longer component state.
- Reload of a valid clip URL reopens the reader (proven in unit test + E2E D).
- Invalid/stale identity (bad id, attempt outside the current result set):
  the reader does not open; a cleanup effect removes the param with REPLACE;
  the Library stays fully usable (unit-tested; no blank app).
- Direct link with clip: reader opens over the default Library view; closing
  deterministically removes the param and remains in Library.

## 8. History semantics

| Action | Semantics |
|---|---|
| Open clip | PUSH (`setSearchParams(next, { replace: false })`) |
| Previous / Next | REPLACE (no new entries) |
| Close (X / Escape / backdrop) | REPLACE removing `clip` |
| Browser Back | POP to the pre-clip Library URL → reader closes |

- One Back from any reader depth (after Next/Next/Previous) returns to the
  exact originating Library URL; verified live: history length constant across
  Next/Next/Previous (unit test + E2E C).
- Close behaves consistently with Back (same resulting URL, no noise).
- Filter changes keep their existing REPLACE semantics; the pagination-depth
  reset effect is keyed only on filter inputs, never on `clip`, so clip state
  cannot trigger filter resets (unit-tested).
- A filter change that excludes the open clip closes the reader (derived
  selection), per packet §19.

## 9. Library state persistence

| State | Mechanism | Loop-preservation |
|---|---|---|
| search/scope/filters/view | URL params (unchanged) | preserved through open/Next/Back |
| pagination depth | component state (mounted); reset effect keyed on filters only | preserved through the review loop (E2E C asserts expanded depth survives) |
| scroll | explicit anchor: saved at clip open (`window.scrollY`), restored on reader close via rAF `scrollTo` | desktop 4000→4000, mobile 2500→2500 (exact) |
| selected clip | URL `clip` param | survives reload; survives Back |

- The reader's focus is moved into the dialog on mount (`tabIndex=-1`,
  `focus({ preventScroll: true })`). This is required for correct scroll
  restoration: a still-focused underlying card is scrolled back into view by
  the browser when the body overflow lock is released, which would override
  the restored position (observed live and fixed).
- Analysis return: leaving to `/dives/analysis/:code` from the reader keeps
  `clip` in the Library URL; browser Back from Analysis reopens the reader.

## 10. Previous / Next

- Ordering source: unchanged — client-side over the **current filtered result
  set** in backend order (`dive_datetime DESC, id DESC`).
- Boundaries disable the buttons (unchanged).
- Live sequence verified (E2E C): open → Next → Next → Previous with URL
  equality after Previous and zero history growth.

## 11. Library reliability contract

- **Loading:** bounded "Loading your dive library…" block (unchanged).
- **Empty:** zero-match state is visually distinct from failure and offers a
  **Clear filters** action (shown when filters/scope deviate from defaults).
- **Retryable error:** failure renders what failed plus a **Retry** button
  that re-runs the load (`reloadKey`); unit test proves recovery.
- Stale/cached state intentionally not invented (API exposes none).
- Player poll indefinite-spinner debt untouched (U4 scope).

## 12. E2E auth foundation

- `e2e/global-setup.ts` + `e2e/helpers/auth.ts`: logs in **once** via the
  app's real `POST /api/v1/auth/login` (`remember_me: true`) using
  `E2E_TEST_EMAIL` / `E2E_TEST_PASSWORD` runtime env vars, and stores the
  session cookie as Playwright `storageState` at
  `frontend/playwright/.auth/user.json` (gitignored in root `.gitignore`).
- `playwright.config.ts`: `globalSetup`, `storageState`,
  `ignoreHTTPSErrors` (self-signed LAN cert), and a second project
  `mobile-chromium` (390×844, isMobile, hasTouch).
- No auth semantics changed; no credentials committed; no production bypass.
- Legacy suite repairs (bounded): `pages.spec.ts` home test renamed to match
  the new home and its weak logo assertion made real (visible-brand check);
  `console-validation.spec.ts` orphaned-API test given a 120s budget (it
  visits 5 routes sequentially); everything else runs unchanged
  **authenticated**.
- New `e2e/tests/library.spec.ts` covers packet Tests A–F (home, clip open,
  exact-context loop, reload, secondary routes, mobile) plus 404 and
  nav-contract assertions. Full suite: **83 passed / 1 skipped (desktop-only
  assertion on mobile) / 0 failed** across both projects (was 34/34 failing).

## 13. Validation

| Check | Command | Result |
|---|---|---|
| typecheck | `npm run typecheck` | PASS |
| unit/component | `npx vitest run` | **61/61 PASS** (was 44; +17 new, 0 lost) |
| production build | `npm run build` | PASS (new bundle `index-CAXEZM4P.js`) |
| lint | `npm run lint` | NOT_CONFIGURED (eslint 9 legacy invocation, pre-existing; unchanged) |
| authenticated E2E | `npx playwright test` | **83 passed / 1 skipped / 0 failed** (desktop + mobile projects) |

Live-behavior proofs captured during E2E/capture runs (preview build):

- `/` → `/dives` (desktop + mobile).
- Exact-context loop: reader open → Next → Next → Previous → Back ⇒ reader
  closed, same `scope/view`, no `clip`, expanded depth intact, scroll
  4000→4000 (desktop) and 2500→2500 (mobile).
- History length constant across Next/Next/Previous.
- Reload with `clip=` reopens the reader.
- Empty state and retryable-error state captured (`s01`, `s02`) using route
  interception only — no production data touched.

## 14. Performance observations

- Thumbnail IntersectionObserver gating, preview cache, and in-flight dedup
  are untouched (diff preserves them verbatim).
- Selected-clip URL state adds no fetches and no broad rerenders: selection is
  a find over the already-memoized `filtered` array.
- No measurable regression observed during E2E runs (page loads, reader open
  latency comparable to U0R baseline); no profiling warranted.

## 15. Deployment

Performed: frontend-only rebuild of `dive-analyser-frontend:latest` from the
canonical tree via `frontend/Dockerfile.deploy` (image `fc9f1c6e4498`) +
`docker-compose up -d --force-recreate --no-deps frontend`. New live bundle:
`index-Dt1jwy4N.js` (index.html md5 `7d4c5fde89c234b1818d52e0b7947ed0`).
Deployed sourcemap first-party sources verified byte-identical to canonical
Git (7/7 key files). Backend/auth/DB/B2 untouched.

Post-deploy live validation against production `https://192.168.1.57:6443`:
- Full authenticated E2E suite: **83 passed / 1 skipped / 0 failed**
  (desktop + mobile projects; one load-sensitive legacy test passed on
  re-run after a transient server I/O spike).
- Live captures: `live-d01-home-lands-in-library.png`,
  `live-m01-home-lands-in-library.png` — `/` lands in the Library on
  production for desktop and mobile.
- Live URLs verified: `/` -> `/dives` (desktop + mobile).

## 16. Remaining work

- **U3 (next):** Clip Viewer core redesign — review hierarchy, player
  dominance, Prev/Next controls, keyboard shortcuts, Details/Analysis
  progressive disclosure. The reader component is intentionally still the
  U0R-era sheet; only its state authority and focus behavior changed here.
- **U4/U5:** player reliability (poll indefinite-spinner), focus trap,
  ArrowLeft/Right navigation, full keyboard model, focus return on close.
- **U6:** delete `/competitions` (and decide `/media/p5-canary`) routes;
  broad legacy-palette sweep (Dashboard/Journey/Analytics/Sessions).
- **U7:** logout/account affordance in the shell (requires touching
  AuthContext — deferred to avoid auth-surface churn in this gate);
  breadcrumb cleanup for deep paths.

## 17. Migration routes preserved

`/dashboard`, `/journey`, `/analytics`, `/sessions`,
`/dives/analysis/:code`, `/media/representatives`, `/media/recall`,
`/media/p5-canary`, `/competitions`, `/login` — all verified reachable (unit +
E2E Test E).
