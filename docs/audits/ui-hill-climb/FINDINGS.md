# Council findings register

Reviewed candidate: `056b5a638876f5b7602334616124eb1bdd984a2c`. No accepted final council matrix yet.

| Source | Finding | Decision and evidence | Next action |
|---|---|---|---|
| Muse round 2 | My dives repeats code/height without date/poster | Confirmed. `AutomaticScore` API returns only ID/code/height/score/exclusion. Existing row links open the exact clip but list identity remains weak. | Find a bounded existing metadata source or a useful visual identity within the unchanged API. Do not deploy backend changes for a local UI review. |
| Muse round 2 | Every By-code card shows sparkline, median/best, histogram/chips | Partially contradicted by current source and served DOM. Sparkline removed in reviewed commit. `.ca-code-details` is closed by default; median/best/chips are hidden until expanded. Own fresh DOM shows average, delta, attempt/session count, last date and summary. Evidence: `browser-screenshot-localhost-mw1wtxiw-2cb51167.png`. | Keep subjective density objection open; next reviewers must inspect collapsed and expanded states separately. No restoring removed decorations to satisfy stale description. |
| Muse round 2 | Member profile statistics dominate | Unresolved description: reviewed source wraps statistics in a closed native disclosure. Reviewer did not open profile child tabs/stats. | Require actual child coverage and distinguish collapsed from expanded. |
| Muse round 2 | Short-height composer/lobby clipping | Unresolved. Earlier coordinator measured composer/Submit within viewport; reviewer says risk and lacks phone thread capture. | Reproduce at exact 844×390 with actual DOM bounds and scroll position before a code fix. |
| Muse round 2 | Room score selection/timer frozen in background | Unresolved; could be hidden-tab timer throttling or state transition. Existing score buttons worked in coordinator normal UI testing, with native automation timeouts separately observed. | Retest foreground own room, rapid score/select/submit, capture phase/deadline/pressed state. No state injection or authentication change. |
| Muse round 2 | Landscape Progress request failed, Retry recovered | Observed transient; cause unknown. A successful retry is not evidence of a layout defect or a resolved networking cause. | Retain failure/recovery; inspect request/status if reproduced. |
| Muse round 2 | Acronyms and technical labels | Partly confirmed: existing DB/SD/HU filters and detailed analysis terminology remain. IQR was already demoted beneath plain variability text. | Review existing labels/help affordance and use concrete wording where it improves action clarity. |
| Muse round 2 | Full coverage and model settings | Review explicitly omits many children/sizes; launch returned variant=xhigh while reviewer says defaults. | Reported 70 scores retained verbatim, but review is incomplete; settings discrepancy unresolved. No passing threshold. |

## Resumed implementation after STOP

Both GLM review records were read after STOP: interrupted, no final matrix or verdict delivered. No interrupted run is counted as approval or failure. Source freeze is lifted for corrections.

- My dives: current-page identities now supply real date/time to the second and video preview, with the existing exact-clip destination. Summary and selection contracts remain unchanged. Reads are limited to the existing 20-row page, at most four concurrent detail requests. This adds up to 20 detail reads per page; the tradeoff is explicit and tested rather than an unbounded scan or invented metadata. Metadata failure preserves the score/selection row. Tests cover concurrency, failure, exact clip identity, repeated codes and null versus zero scores. Actual populated rendering is still unverified after the authentication loss.
- Short-height Judge Room lobby: Back/header, invitation/panel and mode/playlist/Start use two columns at short landscape sizes. Content still scrolls. No claim of fixed scoring behavior or visual score increase until real browser verification.
- Existing acronym help: `dives.modifierHelp` already explains DB/SD/HU/SYNC/DD, and modifier names exist in translations. The objection about discoverability remains subjective; “unexplained” is not established by the code alone.
- New authentication evidence: own account initially returned 200, later `/auth/me` returned 401 JSON and protected evaluation/detail endpoints 401 HTML. Parent independently confirmed login form. This evidence cannot distinguish absent, revoked or expired session. Manual supported login is pending in the parent's visible tab; no automatic credential recovery/authentication change attempted.

Direct resumed build and six targeted tests passed. Full frontend suite is running. Real-data five-size QA, media, WebSocket and new councils are held until an actual authenticated preflight returns 200.
