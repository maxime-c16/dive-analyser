# Round4 findings → structural corrections

Reviewed SHA:6cb6cff77907e59e809c5f4197a0e107d75ebaf4. Muse minimum5/51cells below7; Sol medium4/55; Opus medium2/70. Scores are preserved. Corrections below are not yet independently scored.

| Finding | Cause verified / correction | Evidence |
|---|---|---|
| Landscape floating icon dock covers content | Main journeys use attached, named navigation; Library modes named at every size | run03 actual comparison; five-size captures, no horizontal overflow |
| Player depends on disappearing HUD and gestures | Persistent labeled return/previous/next; attempt summary and actions outside footage; whole frame by default | Real3044video readyState4; navigationNext→3043→Previous→3044; 87player/router/gesture tests |
| My dives imports have identical timestamps | Actual source timestamps are identical and dive_number null; expose canonical clipID, date-only on repeated timestamps, no fabricated sequence | 20distinct IDs from real metadata; duplicate timestamp regression |
| Null score and 0judges dominate My dives | Show Awaiting reviews and retain actual0.0 scores; stable checked In selections semantics | AutomaticScores regressions |
| Dense flat detailed analysis | Progression first and open; secondary analysis closed; 20-row pages; five-column inventory; all secondary metadata remains in attempt drawer | Real201C409rows, firstpage1–20; pagination regression traverses final row |
| Expanding code card stretches neighbour | Grid aligns items at start | Actual844×390 heights189 vs301, no forced equal height |
| Room code field unclear / empty apply | Named input,112B placeholder, disabled empty apply | Real own-room112B one-dive playlist |
| External light derivative prefetch CORS failure | Existing scoped cached-preview retry, still authenticated; two concurrent workers and cleanup retained | Three media tests; own room blob video readyState4 and decoded8.902sec |
| Selected but unsubmitted score silently missed | Explicit deadline instruction; Not submitted reveal; no automatic vote | Source contract preserves deliberate Submit; fresh timed-game QA still required |
| Incorrect awards for unscored players | Remove unsupported award section; preserve full ranking and points | Real own-room results0points, no awards; unit regression |
| Mole vote deadline / silent default / outcome | Countdown, no initial choice, persisted submission state, local confirmed outcome; reject older snapshots | Three room-state regressions; full live mole QA still required |
| Save below fold | Save/Discard in sticky form header | Save visible at all5sizes; header offset below attached navigation |
| Messages short-height / group-sheet clipping | Measured conversation height, fixed nonshrinking sheet controls; remove ornamental entrance motion |844×390history153px/composer bottom381; phonegroup listtop220,sheettop24 |
| Raw translation key / grammar / acronyms | Period translation, proper singular counts, named modifiers and phases from existing domain translations | Tests and actual inventoryheaders |

Factual disagreements retained: collapsed code cards have no sparkline; profile Stats starts closed; spiral score-card artwork is intentional. Today remains a correct calendar date even after an event ends; absence-report permission is server-provided, so no arbitrary permission change. Profile analytics and shared-video directory counts have different scopes, not proven an arithmetic bug. Transient media/network errors recovered but their causes remain unproven. No accessibility certification.

Checks:117files956testsPASS; production buildPASS. Mac global-gate dependencies remain an environmental limitation recorded earlier. Real captures are held privately until sanitization; no scores inferred from images.
