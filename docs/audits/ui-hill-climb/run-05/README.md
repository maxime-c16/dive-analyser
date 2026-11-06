# Run 05 — source frozen, acceptance incomplete

Product source: `2c07abee70c41844d981ebdb9fa95a3f585bbdc4`. Candidate: http://localhost:4317, serving this worktree (Vite process cwd verified). Authenticated owner session verified as maxime, auth/me200 and populated Library200. No authentication changes or exports.

## Changes and checks

- `afc1fbad`: room toolbar sound control, preserving deliberate mute across both video slots and playback start. Sound defaults remain on. Immutable frontend-only note added.
- `2c07abee`: restore the original journey release note; its earlier edit in80cab70a violated catalog immutability. No visual product change in this commit.
-117 files /960 frontend tests pass with Node26 experimental webstorage disabled; initial Node26/jsdom storage failures retained in restart notes. TypeScript and production build pass. Release catalog validation and diff whitespace pass after the immutability correction.

## Actual UI evidence

`capture-index.json` records230 capture attempts, including loaders, missing captures and phase mismatches. It is not a scorecard or230 successful checks. Originals stay private in `/tmp/dive-ui-qa-latest-private.json`; names, signed media and room invitation strings are excluded from this public index.

Actual five-size main captures include populated Library, By code, Progress, Community, My dives, History and Calendar. Actual child captures include profile Dives/Codes/Activity/Achievements, message inbox/thread/recipient/group draft, Calendar detail/schedule form,201C overview/details/progression/inventory and Room phases. Capture existence does not imply visual inspection; the index flags the inspected sets. Early message-group skeleton frames are excluded from settled credit.

Room: both slots explicitly muted through the toolbar before Start; actual video readyState4 and advancing playback verified. Classic6 selected/pressed and Submit exercised; Mole6 submitted, reveal+20points observed, vote initially disabled/no preselection, deliberate Nobody vote and results reached; Code four enabled answers, deliberate selection, reveal and results reached. Exact phases accompany later frames. Classic timing attempts that landed in another phase are rejected, not relabeled as successful.

Analysis:201C eventually loaded409 attempts /91 sessions. Inventory pagination1–20→21–40 verified. Embedded attempt video loaded readyState4, paused at0 with autoplayfalse. No sound played. Ready native-video drawer screenshots and recordingStart repeatedly timeout after15000ms; closing the drawer immediately restores snapshots of the same analysis page. Native screenshot fallback shows the OS prompt “Open this miroapp link?” from the user's other work, not the candidate. That prompt is left untouched. User displaying the panel did not resolve native-video capture.

## Gallery and remaining gate

[GALLERY.md](GALLERY.md) contains five real annotated toolbar comparisons, one per exact viewport. BEFORE is explicitly an earlier candidate with unknown exact SHA; it is not mislabeled the pristine baseline. Original hashes and crop rectangles are in gallery.json. Existing full-page baseline comparisons remain under run-01/run-02/child-comparisons and retain their original source labels.

Remaining: ready drawer/individual player and judging capture under the absolute silence constraint, complete visual QA of all retained child frames, settled group phone recapture, final self matrix, then NEW full Muse xhigh / Sol medium / Sol low reviews on one candidate. No new independent numerical matrix has been delivered for this source. No acceptance claim, push, PR, merge or deployment.
