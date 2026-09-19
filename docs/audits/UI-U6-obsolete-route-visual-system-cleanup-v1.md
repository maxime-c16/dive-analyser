# UI-U6 — OBSOLETE_ROUTE_AND_VISUAL_SYSTEM_CLEANUP_V1 (2026-09-19)

**Status: UI_U6 GREEN (subtractive cleanup; core review loop untouched).**

Worktree branch `ui-u6-route-visual-cleanup-v1` (base = canonical
`uiux-overhaul-pro-app` @ `f74788ce23b8a7de6688db1fc873baec477f7388`,
the accepted U4/U5 HEAD). Task commit `a0cc974`, canonical merge `85e8a07`.
Deployed bundle **`index-CHTyUqYq.js`** + `index-B_p-ckMH.css`, verified
byte-identical to canonical Git (11/11 first-party sourcemap sources for
the key files; deployed JS/CSS md5-identical to the canonical-tree build).

Evidence captures: `docs/audits/evidence-ui-u6-screenshots/` (28 files:
`before-*` rendered from the exact pre-U6 tree @ `f74788c` rebuilt to the
byte-named bundle `index-CbYUMwwV.js`; `after-*` captured live against
production post-deploy; each at 1440px and 390px).

## 1. Preflight / fresh authority

- Canonical repo `/home/mcauchy/dive-analyser`, branch
  `uiux-overhaul-pro-app`, HEAD `f74788ce23b8a7de6688db1fc873baec477f7388`
  — matches the supervisor packet's accepted state (the packet's HEAD is
  authoritative here, not historical: the server canonical is exactly it).
- Worktrees at preflight: main checkout (science thread's uncommitted
  deletions `docs/science/*` + untracked `experiments/landmark_pilot/*` —
  preserved untouched throughout), `subject-resolution-v1`,
  `hurdle-identity-repair` (detached), `ui-u0r/u1u2/u3/u4u5-*` (dormant).
  No active uncommitted UI ownership anywhere: all UI worktrees clean.
- Deployed bundle at preflight: `index-CbYUMwwV.js` (974,402 B JS /
  51,138 B CSS), sourcemap-identified as the U4/U5 tree.
- Production route behavior at preflight: `/competitions` rendered Journey
  inline (duplicate destination, URL stayed `/competitions`);
  `/media/p5-canary` reachable + hidden; unknown paths → usable 404.
- E2E identity: the committed storageState cookie is `localhost`-scoped
  (`da_session`, session 147), so the suite runs against
  `https://localhost:6443` (same production service as
  `https://192.168.1.57:6443`, loopback). Verified valid: full pre-change
  core behavior observed live during before-captures; **zero logins
  performed, zero session revocations, auth semantics unchanged.**
  Dedicated low-privilege E2E identity debt REMAINS (operator follow-up).
- Core revalidation pre-change: Library home, clip open/Next/Previous/Back,
  viewer keyboard/focus, reliability states, mobile flow — all observed
  green at `f74788c`; no concurrent regression found, no repair needed.

## 2. Route inventory BEFORE

| URL | Purpose | Class | Owner | Nav |
|---|---|---|---|---|
| `/` → `/dives` | product entry | CORE (redirect) | router | — |
| `/dives` | Library | CORE | Dives | primary |
| `/dives/analysis/:code` | per-clip analysis | CORE-adjacent | DiveAnalysis | — (from Library/clip) |
| `/dashboard` | Overview | SECONDARY | Dashboard | secondary |
| `/journey` | Journey | SECONDARY | Journey | secondary |
| `/analytics` | aggregate analytics | SECONDARY | Analytics | secondary |
| `/media/representatives` | representatives | SECONDARY | RepresentativeMedia | secondary |
| `/sessions` | sessions | SECONDARY | Sessions | secondary |
| `/media/recall` | media recall | OPERATIONAL | MediaRecall | operations disclosure |
| `/admin` | system pulse | OPERATIONAL | Admin | operations disclosure |
| `/media/p5-canary` | B2/auth playback canary | OPERATIONAL (hidden) | P5Canary | none |
| `/competitions` | **duplicate Journey render** | **OBSOLETE alias** | Journey (shared) | none |
| `/login` | session auth | AUTH | Login | — |
| `*` | usable 404 → Back to Library | CORE | router | — |

## 3. `/competitions` treatment

- Before: `<Route path="/competitions" element={<Journey />}/>` — zero
  unique content, separate route ownership of the same component, URL kept
  `/competitions`, `routeLabels` carried a "Competitions" entry.
- After: `<Route path="/competitions" element={<CompetitionsRedirect/>}/>`
  with `CompetitionsRedirect = Navigate to /journey + location.search,
  replace`. No normal-navigation entry, no duplicate component ownership,
  query string preserved.
- Tests: new unit test (redirect lands on Journey, not-404) + query
  preservation probe (`/competitions?scope=all` → `/journey?scope=all`);
  E2E test E asserts live `/competitions?scope=all` → `/journey?scope=all`.

## 4. P5Canary usage audit → classification: OPERATIONALLY_USED (keep, hidden)

- Source refs: `router.tsx` route (hidden from all nav), `P5Canary.tsx`,
  `router.test.tsx` reachability, `library.spec.ts` reachability.
- Backend: live gated endpoint
  `GET /api/v1/media/playback/canary/revisions` (`media_playback.py:150`,
  gated by `user_auth_enabled && b2_playback_canary_enabled`) — the page is
  its only frontend consumer.
- Docs: P5/P6 media-backbone audits record real-browser evidence via this
  page for the B2 presigned-redirect playback path; U1/U2 + U4/U5 audits
  reference it as the operational/auth/B2 canary harness; PROJECT_STATE
  records "P5Canary and Competitions hidden from nav (routes preserved)".
- No nginx/deploy-script/runbook references; no external bookmarks found
  locally. Removal would destroy the standing media-backbone diagnostic
  surface while saving ~190 lines — diagnostic value wins.
- Final behavior: route unchanged, still hidden from normal navigation,
  breadcrumb single crumb "Player canary" (no fake "Media" parent).
  Component already used app tokens; only its breadcrumb trail changed.
  Documented here as the operational/debug route. No restyle beyond that.

## 5. Navigation / breadcrumb cleanup

- `routeLabels`: removed `/competitions`, `/media` (a fake parent that
  linked to a 404). Kept only labels for reachable destinations.
- `Breadcrumbs()` was path-segment-derived (exposed `Library / analysis /
  5210D`, and a `Media` parent linking to a 404 for all `/media/*` routes).
  Replaced with exported `breadcrumbTrail(pathname)` mapping to
  user-visible IA: deep analysis paths → `Library (/dives) + "<code>
  analysis"`; `/media/*` routes → single current crumb, no fake parent;
  unknown paths → single harmless last-segment crumb.
- `RecentProgress` carried a fake in-component breadcrumb (`Dashboard /
  Sessions / Review` with a cyan "current" marker) — removed with its
  unused `Home`/`ChevronRight` imports.
- Hierarchy preserved: Library primary; Overview/Journey/Analytics/
  Representatives/Sessions secondary; Media recall + System behind the
  Operations disclosure; p5-canary hidden. No new nav, no re-promotion.
- Tests: `breadcrumbTrail` unit table (Library/Journey/analysis/media/
  unknown); nav-hiding assertions retained in `router.test.tsx` and E2E.

## 6. Visual system BEFORE

- Authority: `--app-*` tokens in `index.css` + `bg-app-*`/`text-app-*`/
  `border-app`/`app-panel`/`app-page` utilities (Library/Viewer/DD/Journey
  timeline already native).
- Competing legacy system: hard-coded Tailwind gray/cyan (+ scattered
  blue/purple/teal/yellow) page themes + a 50-line gray/cyan→token
  override shim in `index.css`, a dead Vite `App.css`, a fully dead
  `styles/sync.css` (16 classes, zero JSX references), an unused
  `diving-*` Tailwind palette, Vite scaffold `:root` colors (`#242424`),
  dead `tailwindcss-animate` class names (`animate-in ...`, plugin never
  installed → no-ops).
- Legacy occurrence counts (gray/cyan/hex-signature lines per file):
  SessionDetail 59, Journey 48, Analytics 36, Dashboard 34,
  RecentProgress 33, AvoidedDives 33, JourneyNarrative 24, Sessions 23,
  SyncStatus 21, DiveStory 39, EmotionalStateCapture 9, SyncErrorHandler 8,
  MilestoneNotifier 6, MentalBlockIndicator 4, SyncNotifications 2,
  performanceScoring 1, SessionDirectionIndicator 1, Admin teal 6.

## 7. Token migration performed (no feature redesign)

Convention: neutral/info chrome → app tokens; cyan/blue/purple/teal
decorative emphasis → `--app-accent`; success/warning/error treatments and
true data-series colors stay semantic.

- Dashboard: text/border tokens; `COLORS.primary` cyan→accent; chart grid/
  tooltip/axis hexes → app-token values; spinner/retry → accent; MetricCard
  vestigial 6-color prop collapsed to `accent | success`; Performance/
  SuccessRate badges keep semantic tiers.
- Journey: all text tokens; phase scores/headings/combos → accent; legacy/
  fear blue panels → accent-soft; progress-bar gradients → solid accent/
  success on token tracks; skeletons → elevated panel; dead
  "Start Tracking Emotions" CTA div removed (non-functional control).
- JourneyNarrative: gradient panels → app panels; insight cards → panels;
  trajectory improving/plateauing/failing boxes keep semantic
  green/amber/red (deliberately reverted an over-migration).
- Analytics: `COLORS.primary` + 1M series cyan→accent; all chart chrome
  hexes → token values; summary headings → tokens; success-rate bar
  threshold colors + height/direction series colors kept (data semantics).
- Sessions: headings/table → tokens; icon tiles/dots/"View details" →
  accent; spinner → accent; scope segmented control already token-native;
  success bars keep semantic tiers; neutral borders → app tokens.
- SessionDetail: dialog/cards → panels; close hover → elevated; selected
  dive → accent-soft/accent; "Good" tier blue → accent; sync "S" badge →
  accent; Personal/Best neutral values → accent; tooltip/grid/axis hexes →
  tokens; dialog `rounded-2xl` → `rounded-lg` (core max); removed the
  duplicate "Execution Flow" chart (identical `performance` dataKey as the
  kept "Performance Flow" panel; empty states still covered).
- RecentProgress: gradient week cards → app panels (success week keeps its
  semantic green border); session cards → panels; "Latest" badge → accent;
  trend icons keep semantic colors.
- AvoidedDives: sort buttons active → accent/dark-text; encouragement
  gradient → accent-soft panel; insight/empty/loading → panels; difficulty
  red/amber/yellow tiers kept.
- SyncStatus: sync panel → accent-soft; progress gradient → solid accent
  on token track; stat cells → elevated; connected/error/milestone panels
  keep semantic treatments.
- MentalBlockIndicator: skeleton/buttons → tokens; block/empty states keep
  semantic warning/success treatments.
- SyncNotifications/SyncErrorHandler: gray chrome → tokens; dead
  `animate-in` classes removed; info-blue toast trio kept as the semantic
  info treatment; error detail wells → app-bg.
- MilestoneNotifier: per-type gradient system + `animate-ping` confetti
  removed → single accent-bordered app panel with accent icon tile.
- SessionDirectionIndicator: label → muted; direction chips keep series
  colors (white contrast text on chips kept, justified).
- Admin: `text-teal-300` + progress `bg-teal-300` → accent (6 sites).
- `utils/performanceScoring`: neutral tier `border-gray-600` → `border-app`
  (green/amber/red score tiers unchanged).
- `index.css`: added `bg-app-accent-soft` utility; `:root` scaffold colors
  → app tokens; preserved `#root{min-height:100vh}`; **deleted the
  gray/cyan override shim** after proving zero remaining covered usages.

## 8. Visual system AFTER

- Authoritative source: `frontend/src/index.css` (`--app-*` + utilities).
- No page-local tokens remain; no competing page-wide gray/cyan system.
- Remaining justified colors (semantic/data-series only): success green,
  warning amber/yellow, danger red, info blue (SyncNotifications toasts
  only), 5-tier performance letters, direction series hexes, height series
  hexes, chart volume purple, white contrast text on colored chips/dots.
- Remaining legacy occurrences in retained normal surfaces: none
  unexplained (sweep-verified; see §7). `UNRESOLVED: none`.

## 9. Dead code/style removal (with proof)

| Removed | Size | Proof |
|---|---|---|
| `components/DiveStory.tsx` | 234 lines | zero import/reference in src+e2e+tests |
| `components/EmotionalStateCapture.tsx` | 174 lines | zero import/reference in src+e2e+tests |
| `styles/sync.css` + `@import` | 196 lines | all 16 classes zero-referenced in JSX |
| `App.css` + import | 34 lines | `.logo`/`logo-spin` unused; `#root` rule preserved in index.css |
| gray/cyan shim in index.css | ~50 lines | post-migration sweep: zero covered usages |
| `diving` Tailwind palette | 10 lines | zero `diving-` usages |
| dead `animate-in` classes (3 files) | — | plugin never installed (no-op classes) |
| fake RecentProgress breadcrumb | 8 lines | obsolete internal IA residue |
| dead Journey emotion CTA | 3 lines | non-functional div styled as control |
| duplicate SessionDetail chart | 27 lines | identical dataKey/data as kept panel |

Net diff: **+547 / −1233 lines** across 26 files (39 with evidence).

## 10. Route inventory AFTER

Same as §2 except: `/competitions` is now `COMPAT_REDIRECT → /journey`
(query-preserving); `/media/p5-canary` confirmed `OPERATIONAL (hidden)`;
breadcrumbs no longer expose `/media` or `/dives/analysis` internals. No
route of unknown purpose remains.

## 11. Core regression results (Library/Viewer frozen contracts)

Unchanged and re-proven: `/→/dives`, Library search/filter/scope/view,
`clip=<attempt-id>` authority, open PUSH, Next/Prev REPLACE, Back/Close
exact restoration (scroll + result depth), filtered-result ordering,
playback-rate, keyboard shortcuts, viewer focus/modal contract,
media-status retry semantics, U4/U5 polling terminalization, Analysis
round-trip, 320/390/landscape reflow, 200% zoom, skip link/landmarks/
reduced motion. E2E suites asserting these: **120 passed / 4 skipped /
0 failed on the pre-deploy preview AND 120 passed / 4 skipped / 0 failed
against production** (desktop 62 + mobile 58; skips are the 4 pre-existing
documented ones). Axe L/L2 (Library, ready/error/mobile viewer): 0
critical / 0 serious in both runs.

## 12. Tests / validation

- `tsc --noEmit`: green (one intermediate MilestoneAlert interface error
  diagnosed and repaired).
- vitest: **113/113 across 11 files** (was 110; + redirect behavior,
  + query preservation, + breadcrumb IA table).
- `npm run build`: green → `index-CHTyUqYq.js` (972,843 B) +
  `index-B_p-ckMH.css` (36,590 B).
- Bundle delta vs pre-U6 (`index-CbYUMwwV.js` 974,402 B / CSS 51,138 B):
  JS −1,559 B, CSS −14,548 B (−28%). No new runtime dependencies
  (`package.json`/`package-lock.json` untouched); chunk-size warning
  pre-existing.
- Lint: still NOT_CONFIGURED (pre-existing; not a U6 task).
- E2E identity: stored `localhost`-scoped session 147 reused for every
  run (preview + production + captures); zero logins; session verified
  live after the production run by the passing authenticated suite.
- Note: worktree `node_modules` needed two environment repairs, both
  non-product: copied the canonical gitignored storageState into the
  worktree, and `npm install --no-save @axe-core/playwright@4.13.0`
  (matching the canonical checkout's ad-hoc install; package manifests
  untouched).

## 13. Deployment + live validation

Frontend-only rebuild from the canonical tree
(`frontend/Dockerfile.deploy`, `docker-compose up -d --force-recreate
--no-deps frontend`). Backend/auth/DB/B2 untouched. Live bundle
**`index-CHTyUqYq.js`**: 10/10 key first-party JS sources byte-identical
to canonical Git via deployed sourcemap (CSS verified by md5 against the
canonical-tree build). Live smoke post-deploy: full E2E green (above),
`/competitions?scope=all` → `/journey?scope=all` verified in production,
secondary surfaces + canary + 404 captured (after-* evidence).

## 14. Remaining debt / next gates

- U7 (Analysis progressive disclosure): untouched per scope; SessionDetail
  duplicate-chart removal and breadcrumb IA mapping are compatible with it.
- U8: aggregate-dashboard future; Dashboard/Journey/Analytics/Sessions
  content NOT redesigned here by design.
- OTHER: dedicated low-privilege E2E identity (operator/auth-admin
  follow-up before session 147 expires 2026-10-13); stale `vite preview
  :4173` process from the U4/U5 worktree still listens (dormant, not
  touched); canonical checkout `frontend/dist` + `node_modules/
  node_modules` wart pre-date U6 (left untouched); lint remains
  unconfigured.

## 15. Scope audit

New features: none. Core IA unchanged. Analysis not redesigned. Auth
semantics, media/B2 authority, science, product-data authority: all
unchanged. No forbidden scope breached.
