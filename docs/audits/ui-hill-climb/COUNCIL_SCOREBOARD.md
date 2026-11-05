# Council — numeric scoreboard

Missing cells never pass. “0 below7” on a non-numeric report means there are no numeric cells, not that the reviewer passed. Reported minima are never averages.

| Attempt | Reviewer | SHA noted | Minimum | Cells <7 | Numeric /70 | Missing | Scope / result |
|---|---|---|---:|---:|---:|---:|---|
| 1 | Codex low | 056b5a63 | — | 0 | 0 | 70 | blocked before entry · not a design verdict |
| 2 | Codex low | 056b5a63 | — | 0 | 0 | 70 | one phone Library view · incomplete |
| 2 | Muse xhigh requested | 056b5a63 | 2 | 70 | 70 | 0 | partial; children missing · FAIL; reported scores retained, not accepted fullscope |
| 2 | GLM max oc2 | 056b5a63 | — | 0 | 0 | 70 | interrupted at STOP, no final matrix · no final verdict |
| 3 | Codex low | 056b5a63 | — | 0 | 0 | 70 | preflight only · incomplete |
| 3 | fallback GLM max oc1 | 056b5a63 | — | 0 | 0 | 70 | interrupted at STOP, no final matrix · no final verdict |
|4|Muse xhigh oc1|6cb6cff7|5|51|70|0|FAIL, partial coverage; no fullscope acceptance|
|4|GLM max oc2|6cb6cff7|—|0|0|70|Cancellation requested; explicitly replaced by Opus5.5medium, no verdict|
|4|Claude Opus5.5 medium|6cb6cff7|2|70|70|0|FAIL; per-size mode coverage gaps retained|
|4|fallback GLM max oc1|6cb6cff7|—|0|0|70|Cancellation requested; explicitly replaced by user, no verdict|
|4|GPT6.1Sol medium, Codex account|6cb6cff7|4|55|70|0|FAIL; interaction coverage limits retained|

**Current gate: FAIL.** Round4 has 210 reported numeric cells, 176 below7. No accepted fullscope passing matrix. SHA noted: `6cb6cff77907e59e809c5f4197a0e107d75ebaf4`. Corrections are now uncommitted and have not been independently reevaluated. All three round4 reports have arrived.

## Muse attempt2 — immediately published actual matrix

SHA noted056b5a638876f5b7602334616124eb1bdd984a2c. Minimum2;70/70reported cells below7. Coverage partial, so this is not an accepted fullscope review. [Raw record and gaps](round-02/muse.json). [Factual disagreements](FINDINGS.md) do not change these subjective notes.

| Category |390×844|844×390|768×1024|1024×768|1440×900|
|---|---:|---:|---:|---:|---:|
|Visual hierarchy|3|3|3|4|4|
|Layout and density|2|2|3|3|4|
|Typography|4|3|4|4|4|
|Color and contrast|5|5|5|5|5|
|Spacing and alignment|3|2|3|3|4|
|Navigation and orientation|3|3|3|4|5|
|Control clarity|4|3|4|4|4|
|Terminology and instructions|2|2|2|2|2|
|Component consistency|3|3|3|3|3|
|Task content presentation|2|2|3|3|3|
|Feedback and state clarity|3|3|3|3|4|
|Professional finish|2|2|2|3|3|
|Responsive fit|3|2|3|4|5|
|Next-action discoverability|4|3|4|4|4|

## Critical path: critique → correction → reevaluation

| Critique | Confirmed correction / evidence | Corrected SHA | Reevaluation |
|---|---|---|---|
| Repeated My dives rows lack attempt identity | Real thumbnail/date/time and exact clip link; asynchronous metadata, no fabricated dates. [Phone](run-02/images/my-dives-390x844.png), [all5sizes](run-02/GALLERY.md). |6cb6cff7|Pending round4; no new design score|
| Short landscape lobby crowds setup | Two-column panel/setup/Start; actual844×390Startbottom314. [Annotated pair](run-02/images/room-lobby-844x390.png). |6cb6cff7|Pending round4|
| Foreground score selection fails | Not reproduced: visible own room select6→pressedtrue→Submitenabled→results. Earlier background behavior remains unexplained. |No claimed fix|Pending independent retest|
| Every code card contains sparkline and all secondary statistics | Factual contradiction: Sparkline removed; closed native disclosure hides median/best/chips. [Collapsed pair](run-01/images/02-390x844.png), [open child](child-comparisons/images/code-disclosure-390x844.png). Subjective scores remain untouched. |Already056b5a63|Pending full collapsed/open review|
| Dense terminology / IQR | Plain variability label with IQR secondary; DB/SD/HU help already exists. [Detail pair](child-comparisons/images/analysis-details-390x844.png). Discoverability objection remains open. |Already056b5a63|Pending full review|

Technical tests are separate:951frontendtests/build/typecheck pass for corrected source; they do not validate design. The global local gate has environment limitations. Two GLM members are disclosed as one model family, not three-model diversity.

User-requested active council: Muse Contributor xhigh oc1 + GLM Flash max oc2 + GPT6.1Sol medium provider codex (Codex account). Prior duplicate-GLM history remains recorded; current roster restores three distinct models.

Latest explicit user roster: Muse Contributor xhigh oc1 + GPT6.1Sol medium provider codex + Claude Opus5.5 medium provider claudeAgent. Both GLM cancellation requests are retained historically; no invented verdict or score.

## Muse attempt4 — delivered independently

SHA noted6cb6cff7;minimum5;51/70reported cells below7;19at least7. Coverage incomplete;0accepted fullscope matrices. [Raw matrix/reasons/screenshots](round-04/muse.json), [coverage gaps](round-04/muse-summary.json). Runtime launch tool confirms xhigh; reviewer again describes defaults, discrepancy retained.

|Category|390×844|844×390|768×1024|1024×768|1440×900|
|---|---:|---:|---:|---:|---:|
|Visual hierarchy|6|6|6|6|6|
|Layout and density|6|5|6|6|6|
|Typography|7|7|7|7|7|
|Color and contrast|7|7|7|7|7|
|Spacing and alignment|6|6|6|6|7|
|Navigation and orientation|7|6|7|7|7|
|Control clarity|6|6|6|6|6|
|Terminology and instructions|5|5|5|5|5|
|Component consistency|6|6|6|6|6|
|Task content presentation|6|6|6|6|6|
|Feedback and state clarity|6|6|6|6|6|
|Professional finish|5|5|5|6|6|
|Responsive fit|7|6|7|7|7|
|Next-action discoverability|6|6|6|6|6|

## Sol medium attempt4 — delivered independently

SHA noted6cb6cff7;minimum4;55/70cells below7. [Full per-cell reasons/fix proposals and351capture paths](round-04/sol-medium.json). No after-fix SHA assessed.

|Category|390×844|844×390|768×1024|1024×768|1440×900|
|---|---:|---:|---:|---:|---:|
|Visual hierarchy|6|5|6|6|6|
|Layout and density|5|4|6|6|6|
|Typography|6|6|6|6|6|
|Color and contrast|7|7|7|7|7|
|Spacing and alignment|6|5|6|6|6|
|Navigation and orientation|6|5|6|7|7|
|Control clarity|6|6|7|7|7|
|Terminology and instructions|5|5|5|5|5|
|Component consistency|6|6|6|6|6|
|Task content presentation|5|4|6|6|6|
|Feedback and state clarity|6|6|6|6|6|
|Professional finish|6|5|6|6|6|
|Responsive fit|6|4|7|7|7|
|Next-action discoverability|6|5|6|7|7|

## Opus medium attempt4 — delivered independently

SHA noted6cb6cff7; minimum2;70/70cells below7. [Full per-cell weakest screens and reasons](round-04/opus-medium.json). Coverage gaps remain: detailed collapsed view desktop only; Activity three sizes; Guess the Code1024only; Classic scoring not separately tested1024. No after-fix score claimed.

|Category|390×844|844×390|768×1024|1024×768|1440×900|
|---|---:|---:|---:|---:|---:|
|Visual hierarchy|4|3|4|4|4|
|Layout and density|3|2|4|4|3|
|Typography|4|4|4|4|4|
|Color and contrast|5|5|5|5|5|
|Spacing and alignment|4|3|4|4|4|
|Navigation and orientation|5|3|5|5|5|
|Control clarity|4|4|4|4|4|
|Terminology and instructions|3|3|3|3|3|
|Component consistency|3|3|3|3|3|
|Task content presentation|4|3|4|4|4|
|Feedback and state clarity|4|4|4|4|4|
|Professional finish|3|3|3|3|3|
|Responsive fit|4|2|5|5|4|
|Next-action discoverability|5|3|5|5|5|

2026-11-05 explicit roster change: Opus is replaced for the NEXT round by gpt-6.1-sol low via provider codex. Active council: Muse xhigh, Sol medium, Sol low. Two reviewers now share a model; no three-model diversity claimed. Historical Opus scores remain unchanged. No reviewer is currently running.
