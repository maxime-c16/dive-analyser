# UI-U3 — CLIP VIEWER CORE V1

Date: 2026-09-13
Task: `UI-U3 — CLIP_VIEWER_CORE_V1`
Worktree: `/home/mcauchy/dive-analyser-worktrees/ui-u3-clip-viewer-core-v1`
Branch: `ui-u3-clip-viewer-core-v1`
Initial canonical HEAD: `bf78182a6a79c9c96383a66bed9cea7928142652`
(branch `uiux-overhaul-pro-app`, the accepted U1/U2 final state)
Final canonical HEAD (this gate): `c0a5ae8caa48dc6b8fa6f9e7cbdd09575c640206`
(server-side merge of `ui-u3-clip-viewer-core-v1` @ `0f08b52` over the
concurrently advanced canonical `4f01003b...` Subject Candidate Quality V3;
frontend content byte-identical to the task branch, proven by
`git diff ui-u3-clip-viewer-core-v1 HEAD -- frontend/` = empty).

> Evidence: `docs/audits/evidence-ui-u3-screenshots/` (16 captures:
> d01–d07 desktop, m01–m04 mobile 390×844, s01 failed-media state,
> live-d/m production post-deploy captures).
> All pre-deployment validation ran against the NEW build served by a local
> production preview (`vite preview` on :4173, HTTPS, API proxied to the
> live backend) before deployment, exactly as in U1/U2.

---

## 1. Preflight / fresh authority

- Canonical repo `/home/mcauchy/dive-analyser`, branch `uiux-overhaul-pro-app`,
  HEAD `bf78182a6a79c9c96383a66bed9cea7928142652` — matches the accepted
  supervisor state exactly. Read: `docs/PROJECT_STATE.md` (UI Simplification
  U0R + U1/U2 records present), `docs/audits/UI-U0R-...md`,
  `docs/audits/UI-U1U2-minimal-ia-library-core-v1.md`.
- Worktrees at preflight: main checkout (dirty with the science thread's
  staged-then-unstaged deletions of `docs/science/DIVE_ANALYZER_SUBJECT_RESOLUTION_*`
  + untracked `experiments/landmark_pilot/*` — untouched by U3),
  `subject-resolution-v1`, `hurdle-identity-repair` (detached),
  `ui-u0r-authoritative-rebase`, `ui-u1u2-library-core-v1` (dormant, at
  `c6e9299`). No concurrent thread owns any U3 file: canonical `frontend/src`
  is clean and no frontend edits exist in any worktree.
- Deployed bundle at preflight: `index-Dt1jwy4N.js` (the U1/U2 deployment),
  live at `https://192.168.1.57:6443`.

## 2. U1/U2 contract re-validation (pre-implementation)

Re-proved in canonical source before any edit (and protected by the preserved
unit/E2E suites):

- `/` → `/dives` (redirect, query preserved) — `router.tsx` unchanged.
- `clip=<attempt-id>` URL state on `/dives`, derived selection from the
  filtered result set — unchanged mechanics.
- Open=PUSH (`replace:false`), Previous/Next=REPLACE, close=REPLACE,
  browser Back closes the viewer first — all preserved verbatim in
  `Dives.tsx` (`openClip`/`moveToClip`/`closeViewer`, scroll-anchor effect).
- Pagination-depth reset keyed only on filter inputs — unchanged.
- Primary navigation (Library-first shell) — untouched.

No regressions found; no repairs needed.

## 3. Concurrent ownership

Overlapping files check: none active. The only dirty state in the canonical
main checkout belongs to the science thread (subject-resolution docs +
landmark_pilot experiments), which does not intersect U3 files. U3 committed
only its own paths; the science work was left exactly as found.

## 4. Viewer architecture

Before (U1/U2): the U0R-era `AttemptReader` — a right-anchored side sheet
(`max-w-5xl`, `ml-auto`) with a small video column and a permanently visible
"Attempt details" inspector column. Narrow-inspector presentation.

After:

```
ClipViewer (full-viewport review surface, Library stays mounted underneath)
├─ header: Back to Library · dive code (H2) · date (desktop)
├─ video region: dominant, black stage, native <video> object-contain
└─ bottom panel
   ├─ ClipViewerNavigation: Previous | N / TOTAL (aria-live) + Speed | Next
   ├─ ClipMetadataSummary: height · platform · date, rating badge, score
   ├─ actions: Details (aria-expanded toggle) · Analysis (link)
   └─ ClipDetails (collapsed by default; 2-col definition list)
```

- Component ownership changes:
  - NEW `frontend/src/components/clip-viewer/{ClipViewer,ClipViewerNavigation,
    ClipMetadataSummary,ClipDetails}.tsx`
  - NEW `frontend/src/utils/attemptPresentation.ts` (shared Attempt type,
    performance labels/classes, `modifiersFor`, `attemptScore`,
    `attemptDate`, `attemptSummary`, `attemptDetailRows`)
  - NEW `frontend/src/utils/mediaPreview.ts` (thumbnail preview cache +
    dedup, extracted verbatim from `Dives.tsx`; also used for bounded
    adjacent-clip prefetch from the viewer)
  - MODIFIED `frontend/src/pages/Dives.tsx` (reader replaced by ClipViewer;
    playback-rate state hoisted here so the rate survives clip-to-clip moves
    and close/reopen while the Library stays mounted; `data-attempt-id` on
    cards/rows for focus return; scroll anchor + depth preservation unchanged)
  - MODIFIED `frontend/src/components/DiveVideoPlayer.tsx` (optional
    `playbackRate` prop applied to the media element across source loads;
    overlays restyled from the legacy gray/cyan palette into `--app-*`
    tokens; media lifecycle states and Prepare/Retry semantics unchanged)
- Library remains mounted: the viewer is a `fixed inset-0` overlay inside the
  Dives page; selection stays URL-authoritative; closing restores everything.
- `key={attempt.id}` on the player guarantees clean clip-to-clip transitions
  (no stale poster/status/error from the previous attempt).

## 5. Frozen URL / history contract (unchanged)

| Action | Semantics |
|---|---|
| Open clip | PUSH |
| Previous / Next | REPLACE |
| Back to Library (button) | REPLACE removing `clip` |
| Escape | REPLACE removing `clip` |
| Browser Back | POP to the pre-clip Library URL |
| Analysis entry | Library URL keeps `clip`; Back from Analysis reopens the viewer |

Proven by the preserved U1/U2 unit tests + E2E (library.spec.ts) and the new
U3 tests. N/TOTAL = position in the current filtered result set (backend
order), boundaries disable Previous/Next, no wrap-around, no history growth.

## 6. Keyboard contract

- `Escape` → close viewer (Back-to-Library semantics).
- `Shift+ArrowLeft` / `Shift+ArrowRight` → Previous/Next within the filtered
  result set; no-op at boundaries; suppressed while focus is in an input,
  textarea, select or contenteditable.
- `Space` → toggle play/pause ONLY when the event target is not an
  interactive control (input/textarea/select/button/a/video/slider/combobox/
  contenteditable); space on buttons keeps native activation (proven in E2E
  by the Details button toggling, not the player, while focused).
- Plain `ArrowLeft`/`ArrowRight` are NOT intercepted — native video seek
  keeps its semantics when the player has focus.
- Subtle `Shift+←/→` hints inside the Previous/Next buttons (aria-hidden,
  desktop-only).

## 7. Focus contract

- On open: focus moves into the viewer surface (`tabIndex=-1` section,
  `preventScroll`) — required for U1/U2 scroll restoration, preserved.
- On close (Back button, Escape, browser Back): focus returns to the
  originating Library card via `[data-attempt-id]` lookup with
  `preventScroll` (scroll restoration stays exact). Covered by unit test
  ("closing the viewer returns focus to the originating Library card").
- Previous/Next do not move focus (buttons keep focus through REPLACE).
- Full focus trap / WCAG closure remains U4/U5 (the full-screen overlay is
  the only visible surface; keyboard tabbing stays inside the viewer in
  practice because the Library below is inert under the overlay).

## 8. Playback / playback rate

- Native `<video>` semantics fully preserved: controls, playsInline,
  fullscreen, seek, poster, preload="metadata", original aspect via
  object-contain inside a dedicated black stage. No custom scrubber.
- Playback-rate control: labelled `<select aria-label="Playback speed">`
  with 0.25×/0.5×/0.75×/1×/1.25×/1.5×/2×, default 1×. State lives in
  `Dives.tsx` so the rate persists across Previous/Next and across
  close/reopen during the mounted Library session. `DiveVideoPlayer`
  re-applies the rate on source load and on rate change. Nothing is
  persisted to the backend.
- Media lifecycle presentation: preparing/queued/... states render inside
  the viewer stage with their existing meaning; failed/unavailable shows the
  error + `Retry prepare`; missing/can-request shows `Prepare clip`; no
  linked clip shows a bounded "No linked clip for this attempt." state.
  Decode failure surfaces "Video could not be loaded". Backend semantics
  unchanged; poll-indefinite-spinner debt untouched (U4).

## 9. Responsive composition

- Desktop: video stage is the flexible dominant region (flex-1, capped
  width), controls strip beneath it — hierarchy per packet §25.
- Mobile (390×844): full-width vertical review surface; video stage sized by
  aspect ratio, controls ≥44px touch targets (`touch-target`), no horizontal
  overflow (asserted open AND closed in E2E H).
- The old side-sheet is gone on both.

## 10. Validation

| Check | Command | Result |
|---|---|---|
| typecheck | `npm run typecheck` | PASS |
| unit/component | `npx vitest run` | **85/85 PASS** (was 61; +24 new/updated, 0 lost) |
| production build | `npm run build` | PASS (bundle recorded in §14) |
| lint | `npm run lint` | NOT_CONFIGURED (pre-existing, unchanged) |
| clip-viewer E2E | `playwright test e2e/tests/clipViewer.spec.ts` | **15 passed / 1 skipped (mobile keyboard skip) / 0 failed** |
| authenticated full E2E | `playwright test` | **97–98 passed / 2 skipped / 0 persistent failures** (see note) |

Note: the legacy `console-validation "No unhandled promise rejections"` and
`health-check "memory leaks"` tests remain load-sensitive against the live
server under an ~11-minute full-suite run (documented in U1/U2 §13); each
passes deterministically when re-run in isolation. The U3 viewer introduced
zero console/API errors (`Errors: 0` validations throughout).

Defects found and repaired during validation:
- `ClipDetails` used the `hidden` attribute together with Tailwind's `grid`
  class — the utility's `display:grid` overrode the UA `display:none`,
  leaving Details permanently visible. Fixed by pairing the attribute with
  an explicit `grid`/`hidden` class swap (unit + E2E assert both states).

## 11. Performance observations (preview build, live backend)

- Clip open → video playable (currentSrc + readyState≥1): **~1.2 s** (1193 ms).
- Next → new clip playable: **1.1–1.8 s** (1683 / 1133 / 1809 ms over three
  consecutive ready clips).
- Adjacent clips are pre-warmed through the existing deduped preview cache
  (no new caching architecture). Thumbnail IntersectionObserver gating and
  the Library rendering path are untouched.

## 12. Deployment

Frontend-only rebuild of `dive-analyser-frontend:latest` from the canonical
tree via `frontend/Dockerfile.deploy` (image `dc534c142c3b`) +
`docker-compose up -d --force-recreate --no-deps frontend`. Live bundle:
**`index-CYly4foH.js`** — identical to the canonical-tree build. Deployed
sourcemap first-party sources verified **byte-identical to canonical Git**
for 10/10 key files (Dives, DiveVideoPlayer, all four clip-viewer
components, attemptPresentation, mediaPreview, router, App). Backend/auth/
DB/B2 untouched.

Post-deploy live validation against production `https://192.168.1.57:6443`:

- Full authenticated E2E suite: **98 passed / 2 skipped / 0 failed**
  (desktop + mobile projects).
- Live captures: `live-d01-home-library.png`, `live-d02-viewer-playing.png`,
  `live-d03-back-library.png`, `live-m01-viewer.png`,
  `live-m02-back-library.png` — `/` lands in the Library, the viewer is the
  dominant surface, and Back restores the Library on production for desktop
  and mobile.

## 14. Canonical integration record

| Item | Value |
|---|---|
| Initial canonical HEAD | `bf78182a6a79c9c96383a66bed9cea7928142652` |
| Task branch final commit | `0f08b52` (`ui-u3-clip-viewer-core-v1`) |
| Concurrent canonical advance during U3 | `4f01003b4413a149f33eab0e32c2b30c9485ee86` (science: Subject Candidate Quality V3; no frontend overlap) |
| Final canonical HEAD | `c0a5ae8caa48dc6b8fa6f9e7cbdd09575c640206` |
| Post-merge revalidation | tsc clean, vitest 85/85, build green (`index-CYly4foH.js`) |
| Deployed bundle identity | `index-CYly4foH.js` |
| Deployed↔Git source identity | 10/10 key files byte-identical |

## 15. Remaining debt

- **U4/U5:** poll-failure terminalization (indefinite spinner), focus trap
  hardening + full WCAG closure (skip-to-content, reduced-motion, 200% zoom,
  full keyboard-only review audit), touch-target sweep beyond the viewer,
  broader network/error-state closure.
- **U6:** delete `/competitions` (+ decide `/media/p5-canary`); legacy
  palette sweep (Dashboard/Journey/Analytics/Sessions).
- **U7:** logout/account affordance (AuthContext surface).
- E2E environment note: headless Chromium races `<video>` playback faster
  than real time and can suspend it; the U3 E2E asserts control semantics
  (playbackRate, seek, paused flips) rather than sustained playback.

Evidence inventory (16 captures): `d01-viewer-initial`,
`d02-viewer-playing`, `d03-next-state`, `d04-previous-state`,
`d05-analysis-entry`, `d07-back-restored-library`, `m01-viewer`,
`m02-details`, `m03-next`, `m04-back-library`, `s01-failed-media`
(preview build) + `live-d01-home-library`, `live-d02-viewer-playing`,
`live-d03-back-library`, `live-m01-viewer`, `live-m02-back-library`
(production).

**Gate: `SUPERVISOR_REVIEW_AFTER_UI_U3_CLIP_VIEWER_CORE_V1`.**
