# Task 01 result — local React calendar prototype

Implemented only task 01, in the bound `t3code/calendar-ui-prototype` worktree. No backend, schema, production calendar writes, signup/auth changes, notifications, synchronization, task 02, push, PR or deployment.

## Open the prototype

Start from this worktree:

```sh
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Working local review URL (real Router/Layout, synthetic account and other shell services, no backend required):

<http://127.0.0.1:5173/e2e/fixtures/navigation-review.html?path=/calendar&lang=fr&unread=1>

For the reviewed real-data month, open <http://127.0.0.1:5173/e2e/fixtures/navigation-review.html?path=%2Fcalendar%3Fdate%3D2026-10-01&lang=fr&unread=1>. Use `lang=en` for English. The review harness uses a memory router; its outer browser URL stays fixed as screens change. In the ordinary authenticated dev app the entry is `/calendar`, and filters/date/view/fixture role use real route query parameters. Example: `/calendar?date=2026-11-01&source=competition&view=month&role=coach`. Detail/back preserves those parameters. Existing shell tab memory preserves URL/scroll when switching destinations.

## Design and scope decisions

- Reuse the shell's dark panels, teal accent, typography, borders, focus treatment and safe-area positioning. Date numerals and a continuous agenda provide the visual hierarchy. Month uses a Monday-first labelled grid; compact cells retain accessible event names. Agenda starts at the selected date within the selected month. Today uses Europe/Paris.
- All dev builds show five equal mobile icon-only targets: Library / Messages / Community / Calendar / Evaluations. Calendar uses Lucide CalendarDays; Evaluations retains ClipboardCheck. Labels remain accessible, current-page state and unread badges remain intact. Desktop retains visible labels. **Production keeps its existing four labelled mobile targets**; no Calendar route or empty tab is emitted. The calendar code is lazy and excluded from the production build.
- Phone/tablet details are routed with explicit Back; wide desktop details have an adjacent agenda. Date, source, search, view and fixture role are query parameters. Forms preserve input on validation errors. Create/edit/cancel are local simulations of invited-only outings by a synthetic organizer. Cancellation retains the event and interest. Time/venue edits retain interest and display a change notice. State survives tab switches in memory, resets on reload, and never calls a calendar write API.
- Expand “Prototype controls” to choose assigned beginners, assigned advanced, coach (both), or unassigned. The same group selector filters agenda, month, search and direct detail/edit lookup. Only an assigned member gets their absence action. Interest and absence have independent controls/state; no actual attendance, places, reservation, full-event or waiting-list states exist. Membership neither assigns a group nor grants staff authority. These are UI simulations, **not an authorization implementation**; the local dev adapter makes schedules available to the browser.
- Competition is explicitly synthetic, unverified and needs review. It demonstrates four resource types, three separate deadlines and their meaning. No historical/private URL, live spreadsheet, remote fetching, automatic sync or scoring-rule claim. Dive linking is explicitly simulated and states that video permissions remain unchanged.
- FR/EN prototype strings have a parity test; the shell uses its existing i18next translations. Synthetic event content is bilingual to make the local examples recognizable in either locale.

## Private source adapter

Vite's serve-only middleware reads the supplied ignored `reports/calendar/kcpm-2026-2027/import-bundle.json`, projecting only source key, exact local date/time, timezone, venue and group. It serves a no-store local endpoint. No public asset, source attachment, import bundle, invitation, provenance path or workbook/resource URL is copied into tracked code or production assets. Missing input produces an explicit unavailable/retry state while synthetic outings remain usable.

The supplied `source-checks.json` remains private input; no check is presented as current official verification. Only exact training occurrences are projected. Competition UI uses synthetic resources rather than historical/private links.

Reproduce exact-data verification with Vite running on 5173:

```sh
node frontend/dev/check-calendar-source.mjs
```

Result: **116/116 occurrences match** the supplied bundle, including irregular dates, holiday gaps, group IDs, local times and Europe/Paris. No recurrence expansion or inferred cancellation is performed. Automated browser tests intercept this endpoint with committed synthetic schedules so they do not require private input.

## Validation

From `frontend/`:

```sh
npm run typecheck
npm run test:ci -- src/router.test.tsx src/components/MessagesUnread.test.tsx src/calendar/model.test.ts src/navigation src/i18n/parity.test.ts
npx playwright test -c playwright.calendar.config.ts
npx playwright test -c playwright.navigation.config.ts --project=chromium
npm run build
node dev/verify-calendar-build.mjs
```

- Typecheck: passed.
- Affected unit tests: **81 passed**, including production mapping gate, exact-date conversion, group filtering, malformed dates, FR/EN parity, shell routing, unread badge behavior, tab memory, overlay/action policy and session cleanup.
- Calendar Chromium browser suite: **7 passed**, covering 320/375/390/430 widths, five equal accessible icon targets/current page/unread count, agenda/month, routed detail/back, forbidden group detail, coach and unassigned views, interest/absence independence, form validation/input retention, interest retention through venue edit, cancellation, typed resources, keyboard focus, 200% text, landscape and overlay replacement.
- Existing navigation Chromium regression suite: **all 26 cases passed across the full run (first 22) and a targeted run of the final 4 after refreshing the stale upload fixture**. Covers FR/EN at 320–1440px, scroll/tab memory, messages, overlays, uploads, viewer, evaluation actions and notices. Local fixtures now match current Library, upload and Evaluations contracts/tabs; the storage-denial unit test spies on the actual sessionStorage prototype under Node 26.
- Production build: passed. `dev/verify-calendar-build.mjs` confirms no calendar lazy chunk, local data endpoint, training IDs, prototype controls or five-tab class in emitted JavaScript. Existing Vite large-chunk warning is non-blocking.
- T3 collaborative preview used first, with real supplied training data. Checked 320/375/390/430 CSS-px widths, 844×390 landscape at 32px root text, and 1440px desktop. No horizontal overflow. At 320px the five mobile targets measured about 58.8×52px; landscape enlarged-text targets measured 110×50px. Current-page state, names and unread count were inspected directly.
- Local browser artifacts: `/tmp/calendar-task01-320.png`, `-375.png`, `-390.png`, `-430.png` (synthetic browser-test month views); T3 screenshots in the app's browser-artifacts directory include mobile agenda, month, desktop agenda and desktop detail. Private timetable screenshots are not committed. Test traces are under `/tmp/calendar-task01-tests` and `/tmp/mobile-pr2-playwright` when retained on failures.

## Limits

Desktop browser emulation is not physical iPhone Safari/PWA or VoiceOver proof. Physical-device safe-area/keyboard and icon-recognition review remain necessary before a public release. No persistence, backend authorization, complete club roster, real invitations, notifications, resource verification or actual attendance is claimed. Production work belongs to later tasks and was not started.

Release notes: none — dev-only design prototype

## UI refinement after review

Replaced the three-column Date / Source / Search form with a compact toolbar: grouped month arrows/title/Today, an expandable date picker, direct source buttons and an accessible search field. Mobile wraps filters and search without horizontal page overflow. Added 220ms directional horizontal entry transitions to agenda/month content on previous/next month changes; controls remain stationary and reduced-motion disables animation. Typecheck passes. Eight calendar browser cases pass across the main run (seven) and a targeted rerun after scoping the existing prototype-summary selector; new coverage exercises filtering, search, date jump, both animation directions and reduced motion. T3 preview inspected at 390px and desktop. Still dev-only; no production deploy.

## Small-screen density refinement

Below 1024px the existing shell header provides the Calendar title, so the duplicate page hero is visually hidden (semantic heading retained). Month title opens the date picker and Today action; source/search filters collapse behind a named 44px action with an active-filter indicator. Agenda/Month and create (+ with accessible name) share one row. Prototype controls moved after the useful content on all widths. At 390px the first event starts at y=181px. Added a 320x568 regression asserting the first event fits above bottom navigation without scrolling and the month grid starts before y=240px; also exercises revealing filters and retaining their active indicator. Typecheck and all nine calendar cases passed across the main eight-case run and targeted small-phone/large-text runs. No production release.
