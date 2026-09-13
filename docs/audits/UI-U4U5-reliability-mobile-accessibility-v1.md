# UI-U4/U5 — RELIABILITY_MOBILE_ACCESSIBILITY_V1

Date: 2026-09-13
Task: `UI-U4/U5 — RELIABILITY_MOBILE_ACCESSIBILITY_V1`
Worktree: `/home/mcauchy/dive-analyser-worktrees/ui-u4u5-reliability-accessibility-v1`
Branch: `ui-u4u5-reliability-accessibility-v1`
Initial canonical HEAD: `97f20cf17377ea253b74bba554d598d5a8ea9cb0`
(branch `uiux-overhaul-pro-app`, the accepted U3 final state — matches the
supervisor packet exactly)

> Evidence: `docs/audits/evidence-ui-u4u5-screenshots/` (12 captures:
> d01–d05 desktop library/ready/preparing/transport-error/details,
> m01 390 viewer, m02/m03 320 library+viewer, m04 landscape viewer,
> r01 reduced-motion preparing, z01/z02 200%-zoom-equivalent reflow).
> All pre-deployment validation ran against the NEW build served by a local
> production preview (`vite preview` :4173, HTTPS, `/api` proxied to the
> live backend), exactly as in U1/U2/U3.

---

## 1. Preflight / fresh authority

- Canonical repo `/home/mcauchy/dive-analyser`, branch `uiux-overhaul-pro-app`,
  HEAD `97f20cf17377ea253b74bba554d598d5a8ea9cb0` — matches the accepted
  supervisor state. Read: `docs/PROJECT_STATE.md` (UI-U0R/U1U2/U3 records),
  all three prior UI audits.
- Worktrees at preflight: main checkout (science thread's uncommitted
  deletions + untracked `experiments/landmark_pilot/*` — untouched),
  `subject-resolution-v1`, `hurdle-identity-repair` (detached),
  `ui-u0r-*`, `ui-u1u2-*` (dormant), `ui-u3-*` (dormant at `0f08b52`).
  No active thread owns any U4/U5 file; canonical `frontend/src` clean.
- Deployed bundle at preflight: `index-CYly4foH.js` (the U3 deployment) at
  `https://192.168.1.57:6443` — matches the U3 audit record.
- U3 contract re-proven pre-edit: `/` → Library redirect; `clip=<attempt-id>`
  URL state; open=PUSH; Prev/Next=REPLACE; Back restores exact Library
  context (scroll + depth); viewer video-first full-viewport; playback-rate
  0.25×–2×; keyboard shortcuts (Escape / Shift+←/→ / Space, plain arrows
  left to native seek); Analysis round-trip. Preserved by the untouched
  unit (85) + E2E suites which were re-run green after the changes.
- No regressions found; no repairs needed.

## 2. E2E identity classification and session isolation (packet §31–34)

- **Classification: `PERSONAL_OPERATOR_IDENTITY`.** The production database
  contains exactly ONE user: `app_users` id=1 (`maxime.cauchy93@…`). No
  dedicated E2E identity exists. `E2E_TEST_EMAIL` therefore names Maxime's
  personal account.
- **Backend semantics (unchanged):** `POST /api/v1/auth/login` calls
  `sessions.create_session(..., revoke_existing=True)` — one live session
  per user by design; every fresh login revokes all prior sessions of that
  user. This is why E2E logins routinely logged Maxime out.
- **Mechanism used (non-destructive, already-authorized):** the U3-era
  storageState at `frontend/playwright/.auth/user.json` holds session
  `user_sessions.id=147`, created 2026-09-13 17:03 with
  `remember_me=true` (expires 2026-10-13). Verified live (HTTP 200 on
  `/api/v1/auth/me`) **without any new login**. The harness
  (`e2e/helpers/auth.ts`) already reuses an existing storageState when
  credentials are absent — that path was exercised for the whole U4/U5
  validation cycle. No test in the suite logs out.
- Result: `personal_session_revocation_risk_before: HIGH` (every
  globalSetup with credentials set performed a revoking login);
  `personal_session_revocation_risk_after: NONE` while the stored session
  remains valid (validation runs performed **zero** logins; session 147
  still live at gate end). No auth semantics changed, no credentials
  committed (`.gitignore` line 91 covers `frontend/playwright/.auth/`),
  no production account created.
- Remaining risk / upstream recommendation: when session 147 eventually
  expires (~2026-10-13) or is revoked by a manual login, the next E2E run
  will need one fresh login that revokes the operator browser session
  again. **U6+ recommendation: provision a dedicated low-privilege E2E
  user** (operator action via the existing admin provisioning path — no
  auth-code change required) and set `E2E_TEST_EMAIL` to it.

## 3. Reliability architecture (packet §9–17)

New shared primitives (`frontend/src/utils/a11y.tsx`):
`inertExcept(container)` (inert isolation for everything outside the
dialog ancestor chain, exact restore), `trapTabKey(container, event)`
(bounded Tab/Shift+Tab cycle), `VisuallyHidden`. Deliberately tiny — no
new UI framework.

`DiveVideoPlayer` rewritten around an explicit phase state machine:

```
checking → ready | preparing | prepare-failed | not-cached | transport-failed
```

- **Initial status policy:** bounded automatic retries
  (`INITIAL_STATUS_ATTEMPTS=3`, 600ms/1.2s backoff), then terminal
  `transport-failed` state (`role=alert`, WifiOff icon, "Retry status
  check"). A failed status GET NEVER submits a preparation request.
- **Polling policy:** while the backend reports a legitimate active
  preparation state, 3s polling continues. Each transport failure
  increments a counter; failures 1..4 set `stale` (connection-interrupted
  presentation, spinner continues); at `MAX_POLL_FAILURES=5` consecutive
  failures the interval is torn down (`stopped=true`) and a manual
  "Check status again" action appears. No endless spinner, no silent
  error swallowing.
- **Retry policy:** network Retry actions (`Retry status check`,
  `Check status again`) ONLY re-run the status lookup — proven by tests
  asserting `requestMedia` is never called. `Prepare clip` / `Retry
  prepare` remain explicit user actions via the existing authoritative
  `/api/v1/media/{uuid}/request` endpoint (only where `can_request`),
  guarded by a ref+state flag against double-click/rerender duplicates.
- **Stale policy:** last known authoritative state is preserved during
  transient failures and presented honestly as
  "transcoding — connection interrupted" (`STALE_OR_CACHED`); cleared on
  the first fresh successful status. No stale framing is invented when no
  prior state exists (initial failure goes straight to the error state).
- **Long-preparation policy:** a valid backend preparation is never marked
  failed client-side. After `LONG_PREPARATION_MS=90s` in a legitimate
  active state, presentation honestly becomes "Still preparing this clip"
  with an explicit "Check status now" affordance. No invented progress
  percentages, no cancellation, no backend mutation.
- **Decode-error policy:** the `<video>` error event now surfaces
  "Video could not be loaded" as an accessible `role=alert` state with a
  "Try again" action that reloads the existing source in place. It never
  creates a new media job; preparation authority stays with backend status.
- Backend lifecycle semantics, MediaBlob/MediaRevision/B2 authority:
  untouched. Frontend consumes the existing contracts only.

Library reliability revalidated (U1/U2 behavior preserved): distinct
Loading (`role=status`), Empty (`role=status`), retryable Error
(`role=alert`) + working Retry that refetches; URL filter state survives a
failed request (E2E G asserts `height=3m` intact before and after).

## 4. Viewer modal contract (packet §18–19)

- `role=dialog` + `aria-modal=true` (existed in U3) now backed by real
  isolation: on mount, `inertExcept(dialog)` applies `inert` to every
  sibling at every ancestor level up to `document.body` — the sidebar,
  mobile navigation and the mounted Library become unreachable for focus,
  pointer and assistive technology; exact restore on unmount.
- `trapTabKey` keeps Tab/Shift+Tab cycling within the dialog (wraps at
  both ends; pulls focus back if outside; no-op when focus is legitimately
  inside). Unit + E2E proven (14 forward + 4 reverse Tabs, background
  `inert` asserted).
- Focus lifecycle preserved from U3 (open → dialog focus; close →
  originating card via `data-attempt-id`, `preventScroll`) and extended:
  if the originating card no longer exists, focus falls back to the
  Library search input (never body, never unexpected scroll).
- Escape / Back / browser-Back semantics unchanged (REPLACE removing
  `clip`).

## 5. Skip navigation, landmarks, live regions (packet §20–22)

- Skip link: first focusable element in the shell (`#main-content`,
  visually hidden until focused, visible focus ring, works desktop and
  mobile). `main` gained `id="main-content"` + `tabIndex={-1}`.
- Landmarks: `main` exactly once; sidebar marked `aria-label="Workspace
  sidebar"`; existing nav/headings/button semantics retained (native
  semantics preferred; no ARIA inflation).
- Live regions: player preparation states use `role=status` (polite);
  terminal states (transport failure, prepare failure, decode failure)
  use `role=alert`; Library loading/empty use `role=status`, Library
  error uses `role=alert`; "Media ready." announced once via a
  `role=status` region; N/TOTAL counter keeps its U3 `aria-live=polite`.
  Poll responses that do not change the presented text do not change the
  announced content (asserted by unit test) — no screen-reader spam.

## 6. Reduced motion (packet §24)

The existing `prefers-reduced-motion` media-query gating in
`index.css` (all `ops-*` animations, including `ops-spin`, are wrapped in
`@media (prefers-reduced-motion: no-preference)`) is now enforced by test:
E2E H emulates reduced motion and asserts `animation-name: none` on the
preparing spinner while the named state text stays fully informative and
the loop remains usable. Native video playback untouched.

## 7. Mobile / reflow results (packet §25–28)

- 390×844 (existing U3 viewport): full review loop passes (J/K + prior
  suites); no horizontal overflow open or closed.
- 320px narrow: Library and Viewer `scrollWidth ≤ 320` asserted; Back/
  Previous/Next/Details/Speed all visible and reachable (E2E J).
- Mobile landscape 844×390: video visible, Back/Previous/Next/Speed
  reachable, Back closes cleanly (E2E K).
- 200% desktop zoom: validated via equivalent 640×400 reflow captures
  (z01/z02) plus the 320px assertions; no horizontal page scrolling for
  core content, controls reachable.
- Touch targets: viewer controls keep the existing `touch-target`
  (min 44px) affordance; mobile nav links/buttons unchanged ≥44px;
  filter modifier chips and dense metadata left dense by design.

## 8. Color / non-color signals (packet §29)

Core states pair text + iconography with semantic roles: transport error
(WifiOff icon + text + button), preparation states (labelled text, not
color-only), Library Ready/Linked badges (text label, not just the dot),
rating badges (text label). Focus visibility: global 3px accent outline
on `:focus-visible` (existing) retained; skip link adds its own visible
focus style. No broad legacy-page sweep performed (U6 scope).

## 9. Automated accessibility (packet §30)

Tool: `@axe-core/playwright` **4.13.0** (pinned exact, dev-only, lockfile
committed; added because no a11y automation existed and manual-only
verification cannot regression-proof the core surfaces).

Surfaces scanned: Library, Viewer ready (natural production ready clip,
read-only), Viewer transport-error state (interception), mobile 390
Viewer. Result: **0 critical, 0 serious** on all scanned surfaces.
`region` rule disabled (breadcrumb strip is intentionally outside nav
landmarks; documented as accepted). No moderate/minor findings surfaced
in the scanned states.

## 10. Manual accessibility validation (packet §38)

Performed by the operator-agent against the preview build:

- Keyboard-only core loop (E2E B, desktop): skip link → main → search →
  card → open → Shift+←/→ → Details toggle → Escape → focus on
  originating card. No background leakage (inert + trap asserted).
- Visible focus / focus order: global accent outline verified on cards,
  viewer controls, skip link; order follows DOM order (sidebar → main).
- Viewer focus containment: 14×Tab + 4×Shift+Tab inside dialog (E2E C).
- Focus return: card restored; fallback to search when filtered away
  (unit-tested).
- Native video controls: preserved (U3 contract; controls attribute
  asserted in unit + E2E).
- 200% zoom / 320px / 390px / landscape: captures reviewed (z01, z02,
  m02, m03, m01, m04); no critical overlap; controls reachable.
- Reduced motion: capture r01 + E2E H.
- Screen reader: **NOT_MANUALLY_SCREEN_READER_TESTED** — no screen reader
  exercised locally; semantics verified via roles/labels/live regions and
  axe only, not certified with an AT.

## 11. Performance regression check (packet §40)

Preview build, live backend: clip open → playable ≈1.1–1.3s; Next →
playable ≈1.1–1.8s; Back → Library restored immediately (same session).
Consistent with U3 baselines; the inert/trap work adds O(siblings) DOM
attribute writes on open/close only — no measurable regression. The
adjacent-clip prewarm cache is untouched.

## 12. Validation summary

| Check | Command | Result |
|---|---|---|
| typecheck | `npm run typecheck` | PASS |
| unit/component | `npx vitest run` | **110/110 PASS** (was 85; +25 new, 0 lost) |
| production build | `npm run build` | PASS (`index-CbYUMwwV.js`) |
| lint | `npm run lint` | NOT_CONFIGURED (pre-existing, unchanged) |
| new U4/U5 E2E | `playwright test e2e/tests/reliabilityAccessibility.spec.ts` | **22 passed / 2 skipped / 0 failed** |
| full authenticated E2E | `playwright test` | **120 passed / 4 skipped / 0 failed**, console errors 0, API errors 0 (14.6m) |

Skips: the two desktop keyboard-loop tests skip under the mobile-emulated
project (mobile-emulated Tab traversal through native selects is not
representative; the mobile loop is covered by touch-based tests I/J/K);
2 pre-existing skips unchanged.

Flake note: test C (focus containment) depends on the close commit under
a heavily loaded main thread (471 cards); its close assertion window is
30s. It passed in the final full-suite run and in isolation.

## 13. Deployment

Frontend-only rebuild of `dive-analyser-frontend:latest` from the canonical
tree via `frontend/Dockerfile.deploy` + `docker-compose up -d
--force-recreate --no-deps frontend`. Live bundle: **`index-CbYUMwwV.js`**
— identical to the canonical-tree build. Deployed sourcemap first-party
sources verified byte-identical to canonical Git for the 11 key U4/U5
files. Backend/auth/DB/B2 untouched (no backend rebuild/restart).

Post-deploy live validation against production `https://192.168.1.57:6443`
(using the SAME stored session — zero logins performed, session 147 still
live):

- Full authenticated E2E suite against production: **120 passed / 4
  skipped / 0 failed** (desktop + mobile projects; 98+2 from U3 + this
  gate 22 passed/2 skipped).
- Live captures: `live-d01-library.png`, `live-d02-viewer.png`,
  `live-d03-back-library.png`, `live-m01-viewer.png`,
  `live-m02-back-library.png` (20 total evidence captures).
- Session 147 verified STILL LIVE after the full production run — the
  entire gate performed zero logins and zero revocations.

## 14. Canonical integration record

| Item | Value |
|---|---|
| Initial canonical HEAD | `97f20cf17377ea253b74bba554d598d5a8ea9cb0` |
| Task branch final commit | 630662e59998d1dd8ad9af7ff26f06ff43fb353b |
| Concurrent canonical advance during U4/U5 | none (canonical stayed at 97f20cf through the gate) |
| Final canonical HEAD | 630662e59998d1dd8ad9af7ff26f06ff43fb353b (fast-forward; canonical did not advance concurrently during the gate) |
| Post-merge revalidation | tsc clean, vitest 110/110, build green |

## 15. Remaining debt

- **U6:** `/competitions` alias + `/media/p5-canary` treatment; legacy
  palette sweep (Dashboard/Journey/Analytics/Sessions); dead styles.
- **U7:** Analysis redesign; logout/account affordance (AuthContext
  surface).
- **U8 closure:** dedicated E2E user provisioning (operator action);
  screen-reader manual pass; broader axe coverage beyond the four core
  surfaces; the two load-sensitive legacy tests (console-validation /
  health-check) remain isolated-pass-only (pre-existing, documented since
  U1/U2).

**Gate: `SUPERVISOR_REVIEW_AFTER_UI_U4U5_RELIABILITY_MOBILE_ACCESSIBILITY_V1`.**
