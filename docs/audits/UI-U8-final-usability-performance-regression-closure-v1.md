# UI-U8 — FINAL_USABILITY_PERFORMANCE_REGRESSION_CLOSURE_V1 (2026-09-19)

**Status: UI_U8 GREEN — CLOSED (addendum §17: the dedicated E2E
identity was provisioned by the operator and full production E2E is green
under it. The BLOCKED record below is preserved as the honest
pre-resolution history.)**

Worktree (detached) `ui-u8-final-closure-v1` at
`/home/mcauchy/dive-analyser-worktrees/ui-u8-final-closure-v1`
(base = canonical `uiux-overhaul-pro-app` @ `62181492586fb1437be0057c9c9ac6430699f762`,
the accepted U7 HEAD). Task changes: 3 source files + 2 docs (see §12).
Final architecture/start-here doc: `docs/ui/UI_SIMPLIFICATION_V1_FINAL.md`.
Evidence: `docs/audits/evidence-ui-u8-final/` (10 captures).

## 1. Fresh preflight / authority

- Canonical repo `/home/mcauchy/dive-analyser`, branch
  `uiux-overhaul-pro-app`, HEAD `62181492586fb1437be0057c9c9ac6430699f762`
  — exactly the supervisor packet's accepted state. No drift, no product
  regression from concurrent history.
- Canonical working tree: only science-side uncommitted changes
  (staged deletions under `docs/science/*`, untracked
  `experiments/landmark_pilot/*` + `experiments/subject_resolution/*`
  deletions) — backend/science only, preserved untouched throughout.
  No uncommitted UI ownership anywhere.
- Worktrees at preflight: main checkout + dormant
  `subject-resolution-v1`, `hurdle-identity-repair` (detached),
  `ui-u0r/u1u2/u3/u4u5/u6/u7` (all clean, gates closed).
- Deployed bundle at preflight: live `index-BQ0tlWdF.js` +
  `index-A_H9YTui.css` (U7 tree) in `dive-analyser-frontend-1`,
  image built 2026-09-19T15:52:30Z. Container files match U7 canonical
  build identity. Production/source consistent at preflight.
- `frontend/dist` inside the canonical checkout shows a stale
  `index-CbYUMwwV.js` (U4/U5 era) — gitignored local build artifact,
  not drift, not deployed. Left as-is per layout doctrine (no migration).
- Stale `:4173` vite preview (Sept 13, from the closed U4/U5 worktree)
  still running at preflight — left untouched during validation, stopped
  at closure (see §11).
- E2E identity at preflight: committed localhost-scoped `da_session`
  (session 147, expires 2026-10-13) reused for every run. **Zero logins,
  zero session revocations, auth semantics unchanged.** No dedicated
  identity exists (verified via `manage_user.py list-users`: only
  `user_id=1 maxime.cauchy93@gmail.com`, the personal operator).
- Fresh state differences from U7: none in product code (HEAD identical);
  only the pre-existing science-side uncommitted work noted above.

## 2. U1–U7 contract revalidation (before modifications)

- `tsc --noEmit`: clean. Vitest: **126/126**. `npm run build`:
  reproduces `index-BQ0tlWdF.js` + `index-A_H9YTui.css` (same identities
  as production).
- Full desktop E2E on the base tree (preview `:4175`, zero logins):
  **71 passed / 2 failed**, both failures timeouts, not assertions:
  (a) `analysis K` — hit the known U7 `landmark-unique` moderate note on
  the progression-open surface, then timed out in a subsequent step;
  (b) `health-check` memory-leak probe — `goto networkidle` timeout
  during a slow-backend window. Both re-run green after the repairs
  (§4: 19/19 on the final tree).
- No U1–U7 regression found. Repairs below are closure debt, not
  regressions.

## 3. Dedicated E2E identity closure — BLOCKED item

- Classification: `SAFE_TO_PROVISION_VIA_EXISTING_ADMIN_PATH` — the
  server-local operator CLI `backend/scripts/manage_user.py create-user`
  is the documented provisioning authority (P8): no auth-code change, no
  authorization-rule change, no schema change, non-destructive, least
  privilege (OWNER binding to the already-authorized diver 1, no admin
  role exists in the model at all).
- Per-user single-session enforcement (`sessions.py`: login revokes all
  of that user's sessions) means a second user gets an isolated session
  lifecycle that can never revoke Maxime's session. A dedicated identity
  is the correct and only fix.
- NOT provisioned by this agent: the CLI reads the password via getpass
  (TTY, typed twice, never argv/logged) — provisioning requires one
  interactive operator step, and inventing credential material
  autonomously would violate the packet's "do not improvise" rule.
- Exact operator action (server shell, ~1 minute):
  `docker exec -it dive-analyser-backend-1 python scripts/manage_user.py create-user --email e2e-regression@local --diver-id 1 --display-name e2e-regression --actor-note "UI-U8 dedicated E2E identity"`,
  type a generated password twice at the getpass prompts, store it only
  in the E2E runtime secret mechanism (never in Git), then
  `E2E_TEST_EMAIL=e2e-regression@local E2E_TEST_PASSWORD=<secret>` for
  one login to mint the isolated storageState, and verify Maxime's
  browser session stays valid before/after a full suite run.
- Until then: all U8 validation reused the stored personal session with
  zero logins (no revocation risk taken), exactly as U4/U5–U7 did.
  `BLOCKER_CLASS=DEDICATED_E2E_IDENTITY_REQUIRED`.

## 4. Bounded repairs (diagnose → repair → validate)

Three small closure defects, all validated:

1. **SessionDetail focus trap** (known U7 debt). SessionDetail is a
   reachable modal (`role=dialog aria-modal`, fixed overlay, opened from
   every session card) but had only Escape — no trap, no inert, no focus
   return. Repaired with the accepted `utils/a11y` primitives
   (`inertExcept`, `trapTabKey`), mirroring ClipViewer: focus enters on
   mount, Tab trapped, background inert, Escape closes, focus returns to
   the opening card. Media/playback semantics untouched.
   Proven by scripted probe: focusEntered=true, 15 Tabs contained,
   5/5 background siblings inert while open, 0 leftover inert after
   close, Escape closes. tsc clean.
2. **Journey dead placeholder.** The psychology tab still rendered an
   "Emotional Tracking" teaser inviting emotional-state logging — a
   capability deleted in U6 (`EmotionalStateCapture.tsx` removed). 11
   lines removed, fragment structure preserved (one off-by-one caught
   and repaired same session, tsc clean). No E2E referenced it. The live
   MentalBlockIndicator + psychological profile content is untouched.
3. **Axe `landmark-unique` moderate.** Root cause: `AnalysisSection`
   renders `<section aria-labelledby={buttonId}>` (already a labelled
   region) AND the open panel `<div role="region"
   aria-labelledby={same buttonId}>` — two same-type landmarks sharing
   one label. Fix: dropped the redundant inner `role="region"` (the
   button's `aria-expanded`/`aria-controls` + the labelled section
   already govern the disclosure). No ARIA added, no rules disabled.
   Proven: rerun logs zero `[axe:…]` findings (the note previously
   printed on every progression-open scan).

Net diff: SessionDetail +31/−6, DiveAnalysis 1 line, Journey −11.

## 5. Final route inventory

| URL | Class | Owner | Nav | Purpose |
|---|---|---|---|---|
| `/login` | AUTH | Login | — | session login |
| `/` | COMPAT_REDIRECT | RootRedirect | — | → `/dives` query-preserved |
| `/dives` (+`?clip=`) | CORE | Dives (Library) | Primary Library | product home; clip review |
| `/dives/analysis/:code` (+`?attempt=`) | CORE-adjacent | DiveAnalysis | via Viewer | secondary inspection |
| `/dashboard` | SECONDARY | Dashboard | Review | overview |
| `/journey` | SECONDARY | Journey | Review | narrative/progress |
| `/analytics` | SECONDARY | Analytics | Review | aggregate analytics |
| `/media/representatives` | SECONDARY | RepresentativeMedia | Review | rep. media |
| `/sessions` | SECONDARY | Sessions/SessionDetail | Review | day history |
| `/media/recall` | OPERATIONAL | MediaRecall | Operations | recall diagnostics |
| `/admin` | OPERATIONAL | Admin | Operations | system |
| `/media/p5-canary` | OPERATIONAL | P5Canary | hidden | B2 canary harness |
| `/competitions` | COMPAT_REDIRECT | CompetitionsRedirect | — | → `/journey` query-preserved |
| `*` | FALLBACK | NotFound | — | real 404 + Back to Library |

No route with unknown purpose. Normal-nav visibility matches the IA:
1 primary, 5 secondary, 2 under Operations, 1 hidden operational.

## 6. Final component ownership map

- CORE: `router.tsx` (shell/nav/breadcrumbs), `pages/Dives.tsx`
  (Library+cards), `components/clip-viewer/*` (Viewer),
  `components/DiveVideoPlayer.tsx` (player),
  `utils/attemptPresentation.ts`, `utils/mediaPreview.ts`,
  `utils/a11y.tsx` (inert/trap primitives).
- SECONDARY: `pages/DiveAnalysis.tsx` (attached inspection),
  `pages/Sessions.tsx` + `components/SessionDetail.tsx` (history),
  `pages/Dashboard/Journey/Analytics/RepresentativeMedia.tsx` +
  journey/support components (all import-reachable, §7).
- OPERATIONAL: `pages/MediaRecall/Admin/P5Canary.tsx`.
- Dead-UI sweep result: every page is route-owned; every shared
  component has a live importer (router, pages, or tests); "placeholder"
  hits are input/video placeholders or domain terms; the single fake
  teaser (Journey emotional placeholder) was removed (§4). No remaining
  dead UI. No speculative refactors performed.

## 7. Final visual-system inventory

- Authority: `--app-*` tokens (`index.css`) — reconfirmed; zero legacy
  gray/cyan page themes, zero `sync.css`/`App.css`/`diving`-palette
  references (sweep-verified).
- Remaining literals: token-value duplicates (`#54beab/#98a2aa/#15191c/
  #edf2f4`) used where CSS vars cannot reach (recharts fills, SVG,
  canvas-adjacent props) — same palette as the tokens, justified as
  data-visualization; plus semantic state colors (green/amber/red/blue
  series) and `(min-)touch-target`/contrast treatments. No page-theme
  drift. Unresolved visual debt: none.

## 8. AttemptDrawer classification: JUSTIFIED_SECONDARY_PLAYER

Opened by explicit attempt selection inside Analysis (table, personal
history, progression points). Answers "what is this historical attempt"
without leaving the aggregate workspace (rating, phases, context, media,
raw caption, session link; Prev/Next over the aggregate list). Keeps its
own focus trap + returnFocus. Replacing it with Viewer navigation would
lose aggregate context (Viewer's list is the Library filtered set, not
the Analysis aggregate set) and change history semantics — explicitly out
of scope. Kept, documented.

## 9. Manual screen reader: NOT_MANUALLY_SCREEN_READER_TESTED

Orca exists on the server but there is no graphical session (tty only);
no operable screen reader could drive the app. No certification claimed.
Accessibility evidence instead: keyboard-only E2E loop green, focus
containment assertions green, axe 0 critical/0 serious across 8+
surfaces incl. mobile, reduced-motion enforced + asserted. Per packet
§23 this alone does not block closure.

## 10. Product success tests (scripted heuristic probes + E2E)

- NEW_USER_PATH — PASS: `/` → `/dives` in ~410ms, 0 navigation
  decisions, search + Library heading immediately visible, no overflow;
  one search + one click opens a clip (dialog ~220ms). Captures d01/m01.
- RAPID_REVIEW_PATH — PASS: 14-step sequence (Next×10, Previous×3)
  over a 472-result set: 11 unique clips as expected (revisits on
  Previous), 0 wrong-target, history +1 on open then +0 across 13
  REPLACE moves, rate 1.5 honored, Details opened, Analysis round-trip
  restored the same clip (2768), Library URL+filters restored.
- MOBILE_PATH — PASS: 390×844 + ~320px + 844×390 landscape E2E green;
  captures m01–m03; no overflow; critical controls reachable.
- ERROR_RECOVERY_PATH — PASS: D/E/F/F2/G + analysis H + decode-retry
  E2E green; not-cached → explicit Prepare, transport-failure →
  actionable Retry; capture d06.
- KEYBOARD_ONLY_PATH — PASS: skip→search→open→rate→Next→Previous→
  Details→Analysis→expand→Back→close E2E green; focus transitions
  asserted (dialog entry, card return incl. data-attempt-id=2766).
- ANALYSIS_ROUND_TRIP — PASS: Viewer→Analysis (attempt context in URL)
  →Back restores exact Viewer incl. browser-Back (A–E green, desktop +
  mobile); direct code-only + invalid-attempt fallbacks safe.
- No real user study performed — results are heuristic/manual +
  automated regression evidence, labeled as such.

## 11. Performance observations (uncontrolled env, approximations)

- Library shell (scope=all): ~221ms to interactive search.
- Clip open → dialog: ~220ms; first-open → playable (video
  currentSrc+readyState≥1): ~5.1s cold, Next→playable median ~510ms
  (10 samples 494–583ms), Previous→playable ~536ms, Back-to-clip
  ~1.6s, Back-to-Library immediate.
- Prior baseline (U3/U4): open ~1.1–1.3s, Next ~1.1–1.8s. No material
  regression (Next faster on warm ready clips; first-open dominated by
  media fetch, unchanged architecture).
- Library scale sanity: 48-row scope=all set renders, scrolls, opens,
  restores exactly (probe2: y 3568→3568); E2E asserts 4000/2500 scroll
  restoration. No virtualization indicated; none introduced.
- Console/API smoke: console-validation + api specs green — 0 app
  errors, 0 warnings, 0 API errors across all pages (desktop+mobile);
  no unexplained 4xx/5xx, no duplicate mutations (read-only validation).

## 12. Files changed / commits

Task-branch diff vs base `6218149` (before docs):

- `frontend/src/components/SessionDetail.tsx` (+31/−6): focus-trap
  repair using accepted primitives.
- `frontend/src/pages/DiveAnalysis.tsx` (1 line): drop redundant inner
  `role="region"` (landmark-unique fix).
- `frontend/src/pages/Journey.tsx` (−11): remove dead emotional-state
  teaser placeholder.
- `docs/ui/UI_SIMPLIFICATION_V1_FINAL.md` (new): start-here doc.
- `docs/audits/evidence-ui-u8-final/` (new, 10 captures).
- This audit + PROJECT_STATE U8 section (docs/evidence only).

Commits: task `cef0c1665c24fc48bb47c397897d79e4b6b370db` → canonical
code-merge `1dd8045addd868ec9e3931a33fc84a88a5718a81` (deployment source;
frontend tree frozen here) → docs/evidence merge(s) with identical
frontend tree. No auth/media/science/product-data change. No new product
features; core IA unchanged; analysis semantics unchanged.

## 13. Test totals (final tree, zero logins throughout)

- tsc: clean. Vitest: **126/126**. Build: green,
  `index-zrC4-UyN.js` + `index-A_H9YTui.css` (CSS unchanged).
- Preview E2E desktop: base 71 passed/2 failed (timeouts) → final-tree
  rerun of affected specs 19/19; core contracts re-proven.
- Preview E2E mobile: **69 passed / 4 skipped / 0 failed**.
- Axe: 0 critical / 0 serious everywhere scanned; the one moderate
  (`landmark-unique`) repaired and verified absent; `region` rule
  remains disabled with standing rationale.
- Production: redeployed from committed canonical HEAD (frontend-only);
  bundle/source identity verified (§14); read-only smoke green.
- Full production browser E2E was NOT run: the stored session cookie is
  localhost-scoped and no dedicated identity exists — this is exactly
  the blocking debt (§3). Behavior was proven on the byte-identical
  preview build instead.

## 14. Deployment + source proof + mirror

- Authoritative procedure frozen in `docs/ui/UI_SIMPLIFICATION_V1_FINAL.md`
  (compose has no build section; explicit `docker build -f
  frontend/Dockerfile.deploy` + `up -d --force-recreate --no-deps`).
- Deployed commit: code-merge `1dd8045` (frontend tree frozen; all
  later merges docs-only with identical frontend tree — docs-merge
  `03aa751`, HEAD-record `f571d83`, final canonical HEAD recorded in
  PROJECT_STATE).
  Live bundle `index-zrC4-UyN.js`
  (md5 `138abc98420a2779f1c650231da43b35`) + `index-A_H9YTui.css`
  (md5 `2815236eb28049fc8187361467e84d3e`): both md5-identical to a fresh
  canonical-tree `npm run build`; deployed sourcemap key first-party
  sources (SessionDetail, DiveAnalysis, Journey, Dives, ClipViewer,
  router, DiveVideoPlayer, a11y) byte-identical to Git (8/8).
- Mirror: `mac-mirror` was current at U7 HEAD; server→mirror SSH was
  broken (wrong default key) and mechanically repaired with the
  already-authorized `divesensei_agent_key` (server `~/.ssh/config`,
  IdentitiesOnly; no new access). Verified: fetch works,
  `mac-mirror/uiux-overhaul-pro-app` == canonical HEAD before and after
  the U8 merge (final push recorded below).
- Worktree/preview cleanup: `:4175` worktree preview stopped after use;
  dormant `:4173` (closed U4/U5 gate) stopped; dormant UI worktrees
  `ui-u0r/u1u2/u3/u4u5/u6/u7` removed after proving no unmerged commits;
  `dist`/`node_modules` left per doctrine (gitignored artifacts).

## 15. Remaining intentional debt (non-core, non-blocking)

1. Dedicated E2E identity — BLOCKING for full closure, operator step
   documented in §3 (expires 2026-10-13 for the current session).
2. Lint not configured (pre-existing, all gates).
3. Manual screen-reader pass unavailable (see §9).

## 16. Recommendation: BLOCKED (solely E2E identity)

Every GREEN criterion in packet §50 is met except the dedicated-identity
cluster ("dedicated E2E identity is operational", "no longer depends on
Maxime's personal session", and consequently full production browser
E2E). The product itself is finished: all U1–U7 contracts preserved and
re-proven, all success paths PASS, a11y 0 critical/0 serious, deployment
reproducible from Git, mirror synced, docs frozen. The moment the
operator mints the dedicated user (§3) and one green production run
executes under it, this gate becomes CLOSED_GREEN with no further work.
That moment arrived the same day — see §17 addendum.

## 17. Addendum — identity resolution + CLOSED_GREEN (2026-09-20)

The operator ran the §3 command and provisioned
`e2e-regression@local` (user_id=13, OWNER diver 1, no admin role in the
model). This agent then closed the gate:

- **Isolation proven:** `list-users` before/after every run —
  `user_id=1` keeps `live_sessions=1` throughout (zero logins as Maxime,
  zero revocations). User 13 mints/revokes only its own sessions
  (per-user single-session rule). Maxime's browser session was never at
  risk and never touched.
- **Session lifecycle:** one real `/api/v1/auth/login` per target
  (preview, then production) minted isolated storageStates; no shared
  personal session remains in any E2E path. Credentials live only in
  run-time env, never in Git/audits/screenshots.
- **Test-data drift found and fixed (test-only, no product change):**
  fresh 103C ingestion reordered the Library so `analysis.spec.ts`
  `viewerToAnalysis` no longer opened a 103B first row (6 failures).
  The hardcoded `103B` URL assertion became a generic
  `/dives/analysis/[^/]+?attempt=\d+/` (intent preserved: attempt-context
  round-trip). Standalone reproduction had already shown the round-trip
  itself green for the new clip. `e2e/` is excluded from the vite build;
  the production bundle is unaffected (identity re-verified below).
- **Methodology note (invalid evidence discarded):** two interim reruns
  omitted `E2E_BASE_URL` and hit production unauthenticated (login
  redirect, 6 timeouts each). Those runs prove nothing about the product
  and are excluded from all totals; the agent error is recorded here so
  no future thread repeats it. Always set `E2E_BASE_URL` explicitly.
- **Preview full suite (dedicated identity):** 136 passed / 4 skipped +
  22/22 analysis rerun = effectively 146/146 (4 skips are the standing
  conditional skips), 0 failures, 0 console/API errors.
- **Production full suite (dedicated identity, 142 passed / 4 skipped /
  0 failed, ~14min):** read-only except the container state already deployed; no product-data, media,
  science, or auth mutation.
- **Post-run verification:** production still serves `index-zrC4-UyN.js`
  (md5 re-verified identical to the canonical-tree build); operator
  session still valid; mirror re-synced to the final HEAD.
- Test files changed after the deployment-source freeze: only
  `e2e/tests/analysis.spec.ts` (assertion generalization + comment).
  No app source, no bundle change, no redeploy required.

**Final recommendation: CLOSED_GREEN.** Every packet §50 criterion is
met, including the dedicated-identity cluster. Remaining intentional
debt is non-core: lint not configured (pre-existing), no manual
screen-reader pass (see §9).
