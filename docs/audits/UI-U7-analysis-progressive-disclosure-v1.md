# UI-U7 — ANALYSIS_PROGRESSIVE_DISCLOSURE_V1 (2026-09-19)

**Status: UI_U7 GREEN. Analysis is a secondary inspection surface attached to
clip review: calm first screen, authoritative data only, correct grain always,
exact return to review.**

Worktree branch `ui-u7-analysis-progressive-disclosure-v1` (base = canonical
`uiux-overhaul-pro-app` @ `17143b01d4e5de81994464d20dcc64154941af8a`, the
accepted U6 HEAD). Task commit `d4718cd`, canonical code-merge `ce7c075`.
Deployed bundle **`index-BQ0tlWdF.js`** + `index-A_H9YTui.css`, verified
byte-identical to the canonical Git tree (deployed JS/CSS md5-identical to
the canonical-tree build; deployed sourcemap first-party sources
byte-identical to M1 blobs for DiveAnalysis/ClipViewer/Dives/router).

Evidence captures: `docs/audits/evidence-ui-u7-screenshots/` (8 files:
viewer-before-analysis, first-available 1440/390/320, progression-open,
comparison, unavailable, retry).

## 1. Preflight / fresh authority

- Canonical repo `/home/mcauchy/dive-analyser`, branch
  `uiux-overhaul-pro-app`, HEAD `17143b01d4e5de81994464d20dcc64154941af8a`
  — exactly the supervisor packet's accepted state. No drift.
- Canonical frontend diff `f74788c → 17143b0` is exactly U6 (26 files,
  +547/−1233); `DiveAnalysis.tsx` untouched since before U6. U1–U6 core
  contracts preserved by construction, re-proven by E2E (§12).
- Worktrees at preflight: main checkout (science thread's uncommitted
  deletions under `docs/science/*` + untracked `experiments/landmark_pilot/*`
  — backend/science only, preserved untouched throughout), dormant
  `subject-resolution-v1`, `hurdle-identity-repair` (detached),
  `ui-u0r/u1u2/u3/u4u5/u6-*` (all clean). No active uncommitted UI ownership
  anywhere: safe to continue, no `UI_U7_BLOCKED`.
- Deployed bundle at preflight: `index-CHTyUqYq.js` + `index-B_p-ckMH.css`
  (U6 tree), confirmed live before starting.
- E2E identity: committed `localhost`-scoped `da_session` (session 147,
  expires 2026-10-13) reused for every run — preview + production +
  captures. Read-only probe returned 200 before starting; the passing
  authenticated suites re-verified it live afterward. **Zero logins, zero
  session revocations, auth semantics unchanged.** Dedicated low-privilege
  E2E identity debt REMAINS (operator follow-up before expiry).
- Production reachable for validation; all live checks read-only except the
  authorized frontend container rebuild/recreate (no product-data, media,
  science, or auth mutation).

## 2. Analysis architecture BEFORE

- Route `/dives/analysis/:diveCode` owned by `DiveAnalysis.tsx` (534 lines):
  a per-dive-code **aggregate dashboard**, not a clip inspection surface.
- No attempt context: the Viewer Analysis link was
  `/dives/analysis/${code}` (attempt id dropped); no Back-to-clip control;
  the page auto-opened the AttemptDrawer when `?attempt=` happened to match.
- First screen: code-switcher header, sticky context bar, always-open
  8-column filter panel, insights + context card, **7-cell KPI wall**,
  personal-value history, representative cards, progression chart, period
  comparison, distribution + breakdown, phase panels, attempts table,
  `Analytics {version} · {cache} · {ms}` observability footer.
- Transport and capability states conflated: raw error text with no Retry;
  zero-result views rendered zeroed sections; no unavailable state.
- Duplicate video: AttemptDrawer mounts a full `DiveVideoPlayer` (kept —
  see §7; it mounts only on explicit attempt open).

## 3. Data grain audit

Every current result was classified. There is **no per-attempt scientific
output in the product** (consistent with PROJECT_STATE: `execution_analyzer`
is a stub; Event Logic not evaluable; perception insufficient). All
aggregates are DIVE_CODE_AGGREGATE under the active filter set:

- summary / trend / comparison / breakdowns / phases / insights:
  deterministic analytics service (layer B) → grain DIVE_CODE_AGGREGATE.
- personal-values: versioned heuristic service (layer C, v1, confidence +
  caveats) → per-attempt values inside a code scope (ATTEMPT grain values,
  aggregate context).
- representatives: media authority (poster/proxy readiness) → selected
  ATTEMPTs in aggregate context.
- AttemptDrawer metadata (caption, notes, media state): product metadata,
  ATTEMPT grain — not analysis, kept inside explicit attempt views.
- No SESSION- or ATHLETE_AGGREGATE-scoped claims are rendered as such;
  session weighting is labeled where it applies. No mislabeling found.

## 4. Capability authority table (mandatory)

| CAPABILITY | UI SECTION (before) | SOURCE API/FIELD | GRAIN | AUTHORITY | AVAILABILITY (live 103B) | USER VALUE | U7 DECISION | RATIONALE |
|---|---|---|---|---|---|---|---|---|
| Code header + sample line | header | `dive-analysis.sample` | DIVE_CODE_AGGREGATE | AUTHORITATIVE_AVAILABLE | 187 attempts / 42 sessions | orientation | KEEP_FIRST_SCREEN (as Analysis scope header + grain eyebrow) | authoritative, answers "what am I looking at" |
| Code switcher form | header | router nav | n/a (nav) | AUTHORITATIVE_AVAILABLE | works | jump to another code | KEEP_FIRST_SCREEN + strip `attempt` on submit | prevents cross-code id misattribution |
| Sticky context bar (context+Reset/Filters/Link) | sticky bar | derived | DIVE_CODE_AGGREGATE | AUTHORITATIVE_AVAILABLE | works | context copy | REMOVE_DEAD_PRESENTATION (as a bar; context→header, Reset/Link→Filters) | dashboard chrome; duplicated header |
| Filter panel (8-col, always open) | filters | `analysis_filters` | DIVE_CODE_AGGREGATE | AUTHORITATIVE_AVAILABLE | works | refine scope | KEEP_PROGRESSIVE (collapsed section) | needed but secondary |
| Insights "What changed" (≤4) | insights | `dive-analysis.insights` (deterministic service) | DIVE_CODE_AGGREGATE | AUTHORITATIVE_AVAILABLE | 1 insight (live) | highest-signal change notes | KEEP_FIRST_SCREEN (empty-guarded) | authoritative, review-relevant |
| Mixed/Equivalent context card + split shortcuts | context card | derived counts | DIVE_CODE_AGGREGATE | AUTHORITATIVE_AVAILABLE | mixed (live) | scope honesty | MOVE_TO_COMPARISON | scope framing belongs with history |
| Headline Attempts/Median/Consistency/Trend | KPI wall | `summary`+`trend` | DIVE_CODE_AGGREGATE | AUTHORITATIVE_AVAILABLE | present | core reading | KEEP_FIRST_SCREEN (4-figure key summary + scope caption) | earns prominence |
| Headline Success/DD context | KPI wall | `summary.success_rate/average_dd/dd_coverage_rate` | DIVE_CODE_AGGREGATE | AUTHORITATIVE_AVAILABLE | present | difficulty framing | MOVE_TO_COMPARISON ("Difficulty & success") | secondary to execution reading |
| Headline Best attempt | KPI wall | `summary.maximum/best_attempt_id` | ATTEMPT (in aggregate) | AUTHORITATIVE_AVAILABLE | present | revisit best | MOVE_TO_COMPARISON ("Review best attempt" opener) | action, not headline |
| Personal review priority | personal value | `personal-values` v1 | ATTEMPT values, code scope | AUTHORITATIVE_PARTIAL (heuristic, confidence-labeled) | 187 values (live) | revisit candidates | KEEP_PROGRESSIVE (own section, caveats kept) | useful with its own warnings |
| Representative attempts | representatives | `representativeMediaApi` | ATTEMPT selections | AUTHORITATIVE_AVAILABLE (media state) | 3 (live) | visual anchors | KEEP_PROGRESSIVE (own section; gated on non-empty result) | media-authoritative |
| Progression chart + text summary | progression | `attempts.rolling_median` | DIVE_CODE_AGGREGATE | AUTHORITATIVE_AVAILABLE | 187 pts | trend reading | KEEP_PROGRESSIVE | chart answers one question; text alternative kept |
| Period comparison | comparison | `comparison.previous` | DIVE_CODE_AGGREGATE | AUTHORITATIVE_PARTIAL (needs bounded range; else honest empty state) | null by default (live) | period delta | MOVE_TO_COMPARISON | history, not first screen |
| Score distribution | distribution | `attempts.performance` | DIVE_CODE_AGGREGATE | AUTHORITATIVE_AVAILABLE | present | shape of history | MOVE_TO_COMPARISON | history |
| Context breakdown + tabs | breakdown | `breakdowns[*]` + sample labels | DIVE_CODE_AGGREGATE | AUTHORITATIVE_AVAILABLE | present, small-sample labeled | subgroup reading | MOVE_TO_COMPARISON | history |
| Phase 1 / Phase 2 panels | phases | `phases` (existing labels) | DIVE_CODE_AGGREGATE | AUTHORITATIVE_PARTIAL (live 160 scored · 27 missing) | partial | phase pattern | KEEP_PROGRESSIVE (scored/missing labels kept, never zero-filled) | authoritative where present |
| Attempts table/cards + AttemptDrawer | attempts | `attempts` + media maps | ATTEMPT metadata | AUTHORITATIVE_AVAILABLE | 187 rows | source list + inspection | KEEP_PROGRESSIVE (drawer kept; video mounts only on explicit open) | keyboard-accessible source of every aggregate |
| Observability footer (`Analytics v · cache · ms`) | footer | `observability` | n/a | DEBUG_INTERNAL | always | none for divers | HIDE_FROM_NORMAL_UI (removed; backend logs untouched) | engineering telemetry, not analysis |
| Drawer video player | drawer | media authority (`DiveVideoPlayer`) | ATTEMPT | AUTHORITATIVE_AVAILABLE | per attempt | watch while inspecting | KEEP_PROGRESSIVE with rationale (§7) | explicit-open inspector, existing media lifecycle |
| Temporal landmarks / trajectory / pose / biomechanics | — | none in product | — | AUTHORITATIVE_UNAVAILABLE | none | — | no sections created | no fake present-day functionality |
| Unknown/debug/legacy fields | — | none rendered | — | none present | — | — | nothing to hide | page contained no UNKNOWN_AUTHORITY output |

`user_facing_unknown_remaining`: none. `science_semantics_changed`: none
(no recompute, no threshold, no formula, no API-semantic change).

## 5. Selected-attempt context contract

- `?attempt=<id>` = presentation-only review context (never computation).
  `parseAttemptParam` accepts positive integers only; anything else is null.
- A parsed id resolves against the loaded code result; unresolvable ids
  stay unresolved (`analysis-attempt-mismatch` notice, aggregate view,
  Library fallback). Drawer no longer auto-opens from `?attempt=` (first
  screen stays calm; drawer opens only from explicit action).
- Code switches strip `attempt` (cross-code misattribution impossible).
- Viewer entry: `/dives/analysis/:code?attempt=<id>` + `state.returnTo`
  (exact Library URL incl. filters + `clip=`). Route regex ignores query, so
  breadcrumbs/compat are unaffected.

## 6. Route / Viewer contracts

- Viewer → Analysis: PUSH (Link default) + attempt param + returnTo state;
  unit + live E2E prove context arrival.
- Analysis → Back to clip: first visible control. With returnTo → exact
  stored Library URL; else with a resolved attempt → `/dives?clip=<id>`;
  browser Back also restores the exact Viewer (history preserved).
- Direct `/dives/analysis/:code` (no context): deterministic fallback
  `/dives?q=<CODE>` (stable supported Library search).
- Invalid `attempt=` (non-numeric or foreign id): safe aggregate view, no
  wrong-clip association (unit + live E2E).

## 7. Architecture AFTER / first screen / disclosure

- Order: Back control → scope header (`Analysis · all <CODE> attempts`,
  aggregate line, selected-attempt line or mismatch note, code switcher) →
  optional open Selected-attempt section → key summary (Attempts / Median
  execution / Consistency / Trend + aggregate scope caption) → What-changed
  insights (empty-guarded) → collapsed sections: Filters, Progression,
  Comparison & history (context intro + Difficulty & success + period
  comparison + distribution + breakdown), Phase analysis, Attempts to
  review, Representatives (non-empty-gated), Personal review priority.
- `AnalysisSection` (button + `aria-expanded`/`aria-controls` + region,
  collapsed content unmounted until opened; `touch-target` controls).
- Video: no new player; drawer player retained with rationale — it mounts
  only after the user opens one specific attempt, reuses the existing
  `DiveVideoPlayer`/media authority, and is the only synchronized
  watch-while-inspecting surface (the Viewer stays the primary review
  surface; Analysis links back to it rather than duplicating it).
- Visual system: `--app-*` tokens only; no new theme, no chart family
  changes (one a11y role fix, §10).

## 8. Transport vs capability states

- `LOADING` ("Calculating…") / `READY` / `RETRYABLE_ERROR` (alert + Retry;
  Retry only re-fetches the same read — E2E-unit proves no media POST).
- On success: `AVAILABLE` (full page) / `PARTIAL` (phases scored/missing,
  comparison empty-state, guarded insights/reps/personal) / `UNAVAILABLE`
  (zero-result view: honest panel + clear-filters action, no populated
  sections, filters stay reachable).
- Network failure never renders as "No analysis" and vice versa.

## 9. Mobile / reflow

- Single-column sections, short summaries, collapsible content, readable
  tables/cards; sticky bar removed; touch targets via `touch-target`.
- 390×844 (mobile-chromium project): full flow green. 320px: back control,
  summary, sections usable, `scrollWidth ≤ 320`. 844×390 landscape: controls
  reachable, no page-wide overflow. 200%-equivalent reflow covered by the
  320px pass + preserved U4/U5 reflow architecture (regression suite green).

## 10. Accessibility

- Preserved baseline: heading hierarchy (h1 → section h2 buttons → h3
  content), semantic Back button, `aria-expanded`/`aria-controls` regions,
  visible focus, keyboard-operable charts/drawer/tables, non-color states,
  touch targets, chart text alternatives (kept).
- Repair: interactive `PointTimeline` dropped `role="img"` on its svg (axe
  nested-interactive **serious** — pre-existing chart code, now surfaced on
  the U7 surface); point buttons + text summary carry meaning; read-only
  timelines keep `role="img"`. No scientific interpretation invented.
- Live regions restrained (loading/error polite/atomic; no per-chart spam).
- Axe (`@axe-core/playwright`, region rule disabled with standing rationale):
  analysis-available, progression-open, unavailable — **0 critical,
  0 serious** on desktop and mobile-390 runs.

## 11. Tests / validation

- `tsc --noEmit`: green.
- vitest: **126/126 across 11 files** (was 113; +13 U7 contract tests:
  param parsing, direct/valid/invalid attempt, returnTo, no-auto-drawer,
  code-switch stripping, retry purity, unavailable honesty, observability
  absence, section keyboard, scope labeling; +Viewer/Dives href updates).
  One adjacent Dives href assertion updated for the new contract (legit).
- `vite build`: green → `index-BQ0tlWdF.js` (974,596 B) +
  `index-A_H9YTui.css` (36.22 kB). Delta vs U6: JS +1,753 B (+0.18%), CSS
  −370 B. No new runtime dependencies (`package.json`/lock untouched);
  chunk-size warning pre-existing. Analysis route import graph unchanged
  (no eager cost added to Viewer/Library; collapsed sections mount lazily).
- Preview E2E (worktree bundle, self-signed localhost HTTPS + backend
  proxy): **142 passed / 4 skipped / 0 failed** (desktop + mobile-390; the 4
  skips are pre-existing documented ones). Includes 22 new analysis specs:
  A viewer→analysis context, B back-to-clip exact restore, C browser back,
  D direct-URL fallback, E invalid attempt, F available+partial scope,
  G unavailable, H retry purity, I 320px, J landscape, K axe triple.
- Core regression on preview: full suite green (Library/Viewer/Next/Prev/
  Back, reliability, console, pages, api, websocket).
- Lint: still NOT_CONFIGURED (pre-existing; not a U7 project).

## 12. Deployment (committed-head discipline)

- Integrated task branch to canonical first (`ce7c075`), then built the
  **committed M1 tree** via `frontend/Dockerfile.deploy`
  (`docker build -f frontend/Dockerfile.deploy -t dive-analyser-frontend
  frontend/` — manual tag; the compose frontend service carries no build
  section, and `up --build` alone did not rebuild, diagnosed and corrected).
- Deployed with `docker-compose up -d --force-recreate --no-deps frontend`.
  Backend/auth/DB/B2 untouched.
- Identity: live `index-BQ0tlWdF.js` md5 == canonical-tree build md5;
  live CSS md5 == canonical-tree build md5; deployed sourcemap key
  first-party sources byte-identical to M1 Git blobs (DiveAnalysis,
  ClipViewer, Dives, router; test files correctly absent).
- Live production validation: analysis + clipViewer + library specs
  **52 passed / 0 failed** (desktop + mobile), read-only.
- Worktree env notes (non-product): worktree `node_modules` is a real copy
  of canonical's + `npm install --no-save @axe-core/playwright@4.13.0`
  (package manifests untouched); storageState copied from canonical
  (gitignored); self-signed localhost preview cert in `/tmp`
  (preview-only); worktree preview on :4174 killed after use (the dormant
  U4/U5 :4173 process left untouched).

## 13. Scope audit

No new scientific metrics; no calculation/threshold/authority change; no
media/B2 change; no auth change; no product-data change; no aggregate
dashboard expansion (net first-screen reduction); Details/Analysis boundary
kept (small context header only, no metadata migration). Backend: untouched
(FRONTEND-ONLY). No forbidden scope breached.

## 14. Remaining debt / next gate

- U8: final usability/performance/regression closure (no redesign per
  packet): new-user walkthrough, rapid-review closure, dead-UI sweep,
  dedicated E2E identity (session 147 expires 2026-10-13), manual
  screen-reader pass if available, production/mirror/source consistency,
  final route/component docs, PRODUCT_SUCCESS_TEST.
- OTHER: lint unconfigured (pre-existing); dormant UI worktrees + stale
  `:4173` preview process (left untouched); canonical `frontend/dist` +
  `node_modules/node_modules` warts pre-date U7 (untouched); the
  `landmark-unique` moderate axe note on the open progression view
  (non-blocking, same class as the accepted region rationale).

## 15. Files / commits

- `frontend/src/pages/DiveAnalysis.tsx` (restructure + contract)
- `frontend/src/pages/DiveAnalysis.test.tsx` (+13 U7 tests, section-aware updates)
- `frontend/src/pages/Dives.test.tsx` (Analysis href contract update)
- `frontend/src/components/clip-viewer/ClipViewer.tsx` (attempt+returnTo entry link)
- `frontend/src/components/clip-viewer/ClipViewer.test.tsx` (href update)
- `frontend/e2e/tests/analysis.spec.ts` (new, 11 tests × 2 projects)
- `docs/audits/UI-U7-analysis-progressive-disclosure-v1.md` (this report)
- `docs/audits/evidence-ui-u7-screenshots/` (8 captures)
- `docs/PROJECT_STATE.md` (UI-U7 section appended, science sections untouched)
- Commits: `d4718cd` (task), `ce7c075` (canonical code-merge M1),
  evidence/state commit + final merge recorded in PROJECT_STATE / report.
