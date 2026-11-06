# Populated UI baseline — 2026-11-04

Status: initial design audit, no product changes. Supersedes the e2e-only chat baseline.
Account: owner's existing authenticated T3 default browser profile. No credentials exported.
Scope excludes legacy Overview, Journey, Analytics, Representatives, Sessions, Media recall, System.

## Method and scoring contract

Live browser inspection with screenshots, accessibility trees and selected DOM geometry; source inspection only to distinguish intended behavior from defects. CSS viewport emulation, not physical device testing. Browser zoom unchanged; screenshots may be device-pixel-scaled.

Five repeatable CSS sizes: P phone portrait 390×844; L phone landscape 844×390; TP tablet portrait 768×1024; TL tablet landscape 1024×768; D desktop 1440×900.
Additional spot check: evaluation history at 320×568. Do not claim every possible size or native mobile browser verified.

Scores are subjective design assessments on 12 equally weighted categories: 0 unusable, 3 alpha, 5 usable but uneven, 8 professional, 10 exceptional. Means are descriptive, not empirical user research. A viewport score must improve independently; desktop improvements cannot mask a mobile regression.
Task content presentation means footage for judging/library, conversations for Messages, people for Community and events for Calendar. It replaces the earlier video-specific label so categories apply consistently.
No global product average: child screens would otherwise overweight Evaluations.

## Corrections to early findings

- The judging card's repeated marks are intentional SVG spiral binding, not duplicated score digits. Empty personal score cards are blank by design. Earlier chat scores of 2 for feedback/state clarity based on that diagnosis are withdrawn; corrected to 4. This is recalibration, not an improvement.
- Calendar initially showed an error during ERR_NETWORK_CHANGED. Retry restored populated events. Count recovery as observed; do not file a backend defect from that incident.
- Mobile immersive-player controls auto-hide. Initial screenshots with footage only do not prove navigation is absent.
- Rapid tab-indicator movement during resize is not sufficient evidence of a persistent alignment bug.

## Coverage

Full five-size scored pass: Library grid, Messages inbox/conversation combination, Community directory, Calendar Upcoming, Evaluations My dives, History, judging post-playback, Judge Room entry/lobby.
Additional child inspection: library player at five sizes; member profile Dives at five sizes; member Codes, Activity and Achievements at desktop; calendar event detail and new-event form at phone/desktop; Judge Room playback on phone, scoring on landscape/tablet/desktop and reveal at five sizes.
Not fully verified: every game mode, final game leaderboard, guest joining, all profile subtab sizes, physical keyboard/OS keyboard, screen reader, light mode, all code-analysis drilldowns. Do not count unvisited states as passed.

## Scorecards

### Library

Route: `/dives`

| Category /10 | P | L | TP | TL | D |
|---|---:|---:|---:|---:|---:|
| Visual hierarchy | 3 | 3 | 4 | 4 | 4 |
| Layout and density | 2 | 2 | 4 | 3 | 4 |
| Typography | 4 | 4 | 4 | 4 | 4 |
| Color and contrast | 5 | 5 | 5 | 5 | 5 |
| Spacing and alignment | 3 | 3 | 4 | 3 | 4 |
| Navigation and orientation | 5 | 5 | 5 | 6 | 6 |
| Control clarity | 4 | 4 | 5 | 5 | 5 |
| Terminology and instructions | 4 | 4 | 4 | 4 | 4 |
| Component consistency | 3 | 3 | 3 | 3 | 3 |
| Task content presentation | 3 | 3 | 4 | 3 | 4 |
| Feedback and state clarity | 5 | 5 | 5 | 5 | 5 |
| Professional finish | 3 | 3 | 4 | 4 | 4 |
| **Mean** | 3.7 | 3.7 | 4.3 | 4.1 | 4.3 |

### Messages

Route: `/messages and an existing conversation`

| Category /10 | P | L | TP | TL | D |
|---|---:|---:|---:|---:|---:|
| Visual hierarchy | 6 | 3 | 5 | 5 | 5 |
| Layout and density | 6 | 2 | 4 | 4 | 5 |
| Typography | 6 | 5 | 5 | 5 | 5 |
| Color and contrast | 6 | 6 | 6 | 6 | 6 |
| Spacing and alignment | 6 | 3 | 4 | 4 | 5 |
| Navigation and orientation | 6 | 4 | 5 | 5 | 6 |
| Control clarity | 6 | 4 | 5 | 5 | 5 |
| Terminology and instructions | 6 | 6 | 6 | 6 | 6 |
| Component consistency | 5 | 4 | 4 | 4 | 4 |
| Task content presentation | 6 | 3 | 5 | 5 | 6 |
| Feedback and state clarity | 5 | 4 | 5 | 5 | 5 |
| Professional finish | 5 | 3 | 4 | 4 | 4 |
| **Mean** | 5.8 | 3.9 | 4.8 | 4.8 | 5.2 |

### Community

Route: `/community`

| Category /10 | P | L | TP | TL | D |
|---|---:|---:|---:|---:|---:|
| Visual hierarchy | 3 | 3 | 3 | 3 | 3 |
| Layout and density | 3 | 2 | 4 | 4 | 4 |
| Typography | 5 | 5 | 5 | 5 | 5 |
| Color and contrast | 5 | 5 | 5 | 5 | 5 |
| Spacing and alignment | 4 | 3 | 4 | 4 | 4 |
| Navigation and orientation | 5 | 4 | 5 | 6 | 6 |
| Control clarity | 4 | 4 | 4 | 4 | 4 |
| Terminology and instructions | 4 | 4 | 4 | 4 | 4 |
| Component consistency | 4 | 4 | 4 | 4 | 4 |
| Task content presentation | 3 | 2 | 3 | 3 | 3 |
| Feedback and state clarity | 4 | 4 | 4 | 4 | 4 |
| Professional finish | 2 | 2 | 2 | 2 | 2 |
| **Mean** | 3.8 | 3.5 | 3.9 | 4.0 | 4.0 |

### Calendar

Route: `/calendar (Upcoming)`

| Category /10 | P | L | TP | TL | D |
|---|---:|---:|---:|---:|---:|
| Visual hierarchy | 6 | 4 | 6 | 6 | 6 |
| Layout and density | 5 | 3 | 6 | 5 | 6 |
| Typography | 6 | 5 | 6 | 5 | 6 |
| Color and contrast | 6 | 6 | 6 | 6 | 6 |
| Spacing and alignment | 5 | 3 | 6 | 5 | 6 |
| Navigation and orientation | 6 | 4 | 6 | 6 | 6 |
| Control clarity | 5 | 4 | 5 | 5 | 5 |
| Terminology and instructions | 5 | 5 | 5 | 5 | 5 |
| Component consistency | 5 | 5 | 5 | 5 | 5 |
| Task content presentation | 6 | 4 | 6 | 6 | 6 |
| Feedback and state clarity | 6 | 6 | 6 | 6 | 6 |
| Professional finish | 5 | 4 | 5 | 5 | 5 |
| **Mean** | 5.5 | 4.4 | 5.7 | 5.4 | 5.7 |

### Evaluations — My dives

Route: `/evaluations?tab=dives`

| Category /10 | P | L | TP | TL | D |
|---|---:|---:|---:|---:|---:|
| Visual hierarchy | 4 | 3 | 4 | 4 | 4 |
| Layout and density | 3 | 2 | 4 | 4 | 4 |
| Typography | 5 | 5 | 5 | 4 | 4 |
| Color and contrast | 5 | 5 | 5 | 5 | 5 |
| Spacing and alignment | 4 | 3 | 4 | 4 | 4 |
| Navigation and orientation | 5 | 4 | 5 | 6 | 6 |
| Control clarity | 4 | 4 | 4 | 4 | 4 |
| Terminology and instructions | 3 | 3 | 3 | 3 | 3 |
| Component consistency | 4 | 4 | 4 | 4 | 4 |
| Task content presentation | 3 | 2 | 3 | 3 | 3 |
| Feedback and state clarity | 4 | 4 | 4 | 4 | 4 |
| Professional finish | 3 | 3 | 3 | 3 | 3 |
| **Mean** | 3.9 | 3.5 | 4.0 | 4.0 | 4.0 |

### Evaluations — History

Route: `/evaluations?tab=history`

| Category /10 | P | L | TP | TL | D |
|---|---:|---:|---:|---:|---:|
| Visual hierarchy | 5 | 3 | 5 | 5 | 5 |
| Layout and density | 4 | 2 | 4 | 4 | 4 |
| Typography | 5 | 5 | 5 | 4 | 4 |
| Color and contrast | 6 | 6 | 6 | 6 | 6 |
| Spacing and alignment | 4 | 3 | 4 | 4 | 4 |
| Navigation and orientation | 5 | 4 | 5 | 6 | 6 |
| Control clarity | 4 | 4 | 4 | 4 | 4 |
| Terminology and instructions | 4 | 4 | 4 | 4 | 4 |
| Component consistency | 4 | 4 | 4 | 4 | 4 |
| Task content presentation | 4 | 3 | 4 | 4 | 4 |
| Feedback and state clarity | 5 | 5 | 5 | 5 | 5 |
| Professional finish | 3 | 3 | 3 | 3 | 3 |
| **Mean** | 4.4 | 3.8 | 4.4 | 4.4 | 4.4 |

### Evaluations — Judging

Route: `/evaluations?tab=judge (loaded post-playback state)`

| Category /10 | P | L | TP | TL | D |
|---|---:|---:|---:|---:|---:|
| Visual hierarchy | 5 | 5 | 5 | 5 | 5 |
| Layout and density | 4 | 5 | 4 | 4 | 4 |
| Typography | 5 | 5 | 5 | 5 | 5 |
| Color and contrast | 6 | 6 | 6 | 6 | 6 |
| Spacing and alignment | 4 | 5 | 4 | 4 | 4 |
| Navigation and orientation | 6 | 6 | 6 | 6 | 6 |
| Control clarity | 4 | 4 | 4 | 4 | 4 |
| Terminology and instructions | 5 | 5 | 5 | 5 | 5 |
| Component consistency | 4 | 4 | 4 | 4 | 4 |
| Task content presentation | 6 | 4 | 7 | 7 | 6 |
| Feedback and state clarity | 4 | 4 | 4 | 4 | 4 |
| Professional finish | 3 | 3 | 3 | 3 | 3 |
| **Mean** | 4.7 | 4.7 | 4.8 | 4.8 | 4.7 |

### Judge Room — entry and lobby

Route: `/room and /room/:code`

| Category /10 | P | L | TP | TL | D |
|---|---:|---:|---:|---:|---:|
| Visual hierarchy | 4 | 3 | 4 | 4 | 4 |
| Layout and density | 4 | 2 | 4 | 4 | 4 |
| Typography | 5 | 5 | 5 | 5 | 5 |
| Color and contrast | 5 | 5 | 5 | 5 | 5 |
| Spacing and alignment | 4 | 3 | 4 | 4 | 4 |
| Navigation and orientation | 3 | 3 | 3 | 4 | 4 |
| Control clarity | 4 | 3 | 4 | 4 | 4 |
| Terminology and instructions | 2 | 2 | 2 | 2 | 2 |
| Component consistency | 3 | 3 | 3 | 3 | 3 |
| Task content presentation | 3 | 2 | 3 | 3 | 3 |
| Feedback and state clarity | 3 | 3 | 3 | 3 | 3 |
| Professional finish | 2 | 2 | 2 | 2 | 2 |
| **Mean** | 3.5 | 3.0 | 3.5 | 3.6 | 3.6 |


## Findings and first overhaul increments

| ID | Priority | Observed problem | Proposed change | Acceptance evidence |
|---|---|---|---|---|
| UI-01 | High | At 390px, Library has four ~84px-wide cards; long dive names wrap into three lines. Header, view strip, Add videos row and search occupy roughly 300px before content. | Use a deliberate mobile card minimum and compact header; move secondary filtering behind one control. | Same populated day: readable names, distinguishable attempts, first content visible earlier, no loss of filters. |
| UI-02 | High | Phone landscape keeps the floating navigation and tall desktop-like page headers. Messages composer is outside the initial viewport. Evaluation lists start near the bottom. | Add a short-height shell and constrain conversation height to available viewport; compact section navigation. | 844×390 inbox and open thread show actionable content; composer remains reachable without being covered; list items can scroll above navigation. |
| UI-03 | High | Evaluation My dives repeats code, zero judges and an inclusion switch in large cards, with no thumbnail/date to distinguish repeated attempts. History repeats broad cards with tiny content. | Use compact attempt rows with identity, date, media preview and score state; secondary jury details expand locally. | Two attempts of the same code are distinguishable without opening each; no rating writes during browser checks. |
| UI-04 | High | Judging uses a large blank physical score card, plus separate half-point toggle and numeric grid; controls and unused panel area compete with footage. | Make the selected numeric score and half-point interaction primary; retain domain identity with restraint. | 0, 0.5, 9.5, 10 and unset are visually distinct; draft changes do not submit; footage and Confirm remain usable in all five viewports. |
| UI-05 | Medium | Community podium, crown and avatar ornaments dominate the first screen; directory appears much later on phone. | Put people and recent shared dives first; compress rankings into useful rows. | Find a member and open their dives in one visible section; ranking period/category remain accessible. |
| UI-06 | Medium | Main pages mix square teal CTAs, outlined boxes, round icon buttons, pills, floating navigation and multiple heading scales. Evaluations desktop title is smaller than its mobile title. | Establish shared type, spacing, control and surface tokens, then migrate main journeys. | Consistent primary/secondary actions and heading hierarchy across all scored screens. |
| UI-07 | Medium | Member profile spends substantial vertical space on stats, member metadata and a minimally annotated activity chart before shared dives. Code cards repeat average/median/best, histogram, score chips and sparkline. | Prioritize shared footage and a small meaningful summary; progressively disclose metrics. | Useful footage visible earlier; selected code/period scope remains clear; charts have readable units and time context. |
| UI-08 | Medium | Calendar has useful populated content but oversized next-event presentation and many bordered surfaces. Event detail stacks an RSVP, location/attendees, explanatory copy, follow/export and organization panels. | Preserve event/date clarity; reduce boxing and secondary prominence. | Upcoming event/time/place and attendance state are scannable; administrative actions remain discoverable. |
| UI-09 | High | Judge Room create request took ~11.6s in the observed run; button only dimmed. Mode names on the entry page are decorative text, not selectors. My shadow is unexplained. | Show pending progress/recovery and make setup choices explicit; clarify simulated participants and shadow behavior at the control. | User knows room creation is in progress and where mode is chosen; repeated click cannot create duplicate rooms. Latency is one observation, not a benchmark. |
| UI-10 | High | Judge Room lobby at 844×390 visibly clips mode/source controls and poster strip. Entry page's bottom navigation overlaps join area at initial scroll. Fullscreen room states expose no clear exit in inspected view. | Build a scrollable short-height lobby and a persistent room exit/back affordance. | All setup controls reachable; start remains available; leaving is discoverable in lobby, playback and reveal. |
| UI-11 | Medium | Room reveal uses bot-personality quotes, chilli reaction text, HIGH/LOW flags and widely separated Next. Scoring loses footage context. | Use a coherent game presentation with clear phase, current dive and outcome; reduce canned decorative copy. | Playback → scoring → reveal remains understandable without relying on animations; selected and unsubmitted scores are clear. |

## Child-page observations

- Library player: footage-first mobile mode and different desktop/tablet sidebars are intentional. Needs separate tap-to-reveal, next/previous and return-flow testing before calling hidden controls a defect.
- Library By code: phone card combines a thumbnail, delta, sparkline, average, median, best, attempt/session count, histogram and many individual score chips. Useful data, weak prioritization.
- Library Progress: phone filter expansion can occupy most of the first viewport before the actual trend summary.
- Code analysis overview: populated attempt scatter plot, rolling median, shaded range, peaks and dips are crowded on phone; numerical summary and period/height controls compete. Desktop makes more useful use of width.
- Detailed analysis initially returned HTTP 500 from /api/v1/dive-analysis/201C; Retry returned 200 and loaded 409 attempts across 91 sessions. Phone body inspected after recovery: dense metric blocks, IQR terminology, and an unavailable period comparison asking for a bounded date range. Record as intermittent failure with successful recovery; cause unverified. No loaded desktop-body score assigned.
- Member Dives profile: five-size pass; avatar framing and metadata pills receive disproportionate space. Activity subtab showed an empty state despite populated dives, which may be a different data contract; no data bug asserted.
- Member Codes subtab: desktop cards repeat multiple statistical summaries and small charts. Achievements showed a low-emphasis progress treatment and substantial panel space; animated/loading content needs settled follow-up before rating all badges.
- Calendar new-event form: phone and desktop inspected without saving. Functional labels exist, but layout reads as a long stack of equally weighted inputs. Viewport emulation does not verify the OS keyboard.
- Calendar event detail: phone and desktop inspected; no RSVP, follow, schedule or cancellation changes made.
- Evaluation jury panel action was clicked for an attempt with zero judges; no populated jury was verified. Do not represent this as tested with real jury data.
- Judge Room: one audit room created and its Classic game started without inviting anyone or submitting a score. Inspected lobby, playback, scoring and first reveal. Server rooms expire after six hours without activity; no delete endpoint used. Other modes, guest entry, full game leaderboard and durable game results remain unverified.

## Repeatable hill-climb loop

1. Pin the candidate app version, account, viewport, route, selected scope and content date. Live deployment SHA was not retrieved in this audit; do not attach local HEAD as proof of live code.
2. Capture settled before/after states for the same task. Ignore entrance-animation frames and transient loading counts.
3. Run: find attempt → open footage → return; select judging draft → cancel; open conversation → reach composer; find member → open shared footage; inspect upcoming event → return; room setup → playback → score-state review.
4. Re-score only affected categories, with a reason tied to rendered behavior. Keep this baseline immutable; append an iteration record.
5. Require no category below 7, mean at least 8, at every target viewport before calling the main UI professional. This is a design target, not a claimed result.
6. Keep functional checks separate: keyboard focus, touch targets, clipping/overflow, loading/error recovery, correct identity/scope, and no unintended writes.
7. For code changes, use docs/AGENT_ENGINEERING.md and the relevant CI tier; user-visible release notes required. No product tests needed for this audit-only document.

## Iteration log

| Iteration | Scope | Before | After | Evidence |
|---|---|---|---|---|
| 0 | Populated baseline | e2e-only provisional chat | this report | Live T3 browser visual inspection, owner session, five-size matrix |

Private media and conversation screenshots remain in host browser artifacts, outside version control. This report intentionally contains no credentials, session values, private message text, or audit room invitation code.

