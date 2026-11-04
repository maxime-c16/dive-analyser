# UI hill climb — 14-category contract

2026-11-04. Owner-approved implementation and council loop. Companion: UI_PROFESSIONAL_BASELINE_2026-11-04.md.

## Baseline matrix

Conservative **lowest observed screen score** per category at each viewport, across the eight scored screen groups in the companion audit. Not an average and not council scores. Rows 13–14 are newly assessed from the same observed layouts. This aggregation makes the weakest screen visible; detailed original screen matrices remain unchanged.

| Category /10 | Phone 390×844 | Landscape 844×390 | Tablet 768×1024 | Tablet 1024×768 | Desktop 1440×900 |
|---|---:|---:|---:|---:|---:|
| 1. Visual hierarchy | 3 | 3 | 3 | 3 | 3 |
| 2. Layout and density | 2 | 2 | 4 | 3 | 4 |
| 3. Typography | 4 | 4 | 4 | 4 | 4 |
| 4. Color and contrast | 5 | 5 | 5 | 5 | 5 |
| 5. Spacing and alignment | 3 | 3 | 4 | 3 | 4 |
| 6. Navigation and orientation | 3 | 3 | 3 | 4 | 4 |
| 7. Control clarity | 4 | 3 | 4 | 4 | 4 |
| 8. Terminology and instructions | 2 | 2 | 2 | 2 | 2 |
| 9. Component consistency | 3 | 3 | 3 | 3 | 3 |
| 10. Task content presentation | 3 | 2 | 3 | 3 | 3 |
| 11. Feedback and state clarity | 3 | 3 | 3 | 3 | 3 |
| 12. Professional finish | 2 | 2 | 2 | 2 | 2 |
| 13. Responsive fit | 3 | 2 | 4 | 4 | 5 |
| 14. Next-action discoverability | 4 | 3 | 4 | 4 | 4 |

## Exit contract

Implement main UI and child journeys, excluding the named legacy pages. Freeze these 14 categories; no weakening or averaging away failures. Each council member independently evaluates every target viewport and relevant child screens, with screenshots and task evidence, and submits 70 numeric cells plus findings and coverage. A cell is the lowest screen score in its coverage. Untested means unverified, never a passing 7. Approval requires every member's 70 cells >=7 against the same final commit and running candidate. Fix then start fresh delegate_task reviews; retain every round. No invented scores or coercion to approve.

Council: Codex second gpt-6.1-sol low; oc1 opencode-go/muse-spark-1.3-contributor variant=xhigh; oc2 opencode/glm-5.3-flash variant=max. Explicit user fallbacks: either named Muse Contributor xhigh or GLM Flash max via oc1/oc2 if a requested council member fails. Record substitution and failures, never silently change providers/settings.

Coordinator: Codex second gpt-6.1-sol reasoningEffort=medium. User explicitly authorizes coordinator delegation to those council members. No other agents. First verify own browser tools and /account shows maxime, then each reviewer's own browser tab/session likewise; do not export cookies/passwords or bypass auth. Preview profile default was signed in as maxime in parent. Profiles may or may not share across threads: child must prove it.

Candidate verification: run frontend from worktree using supported Vite/API proxy or project-supported preview; production app alone cannot verify local changes. Do not modify live dirs, deploy unmerged code, or repoint production assets. Reviewers must inspect candidate URL AND populated account identity. If session sharing fails, investigate supported browser profile flow; report concrete blocker rather than audit empty/test data or fabricate verification.

PR: include per-run commit, candidate URL/version, 14×5 matrix for every reviewer, initial→each iteration→final changes, evidence links, checks, objections/fixes, actual model/provider/settings, release note and services. Read file-pr skill before filing; link PR next tool call. No merge/deploy requested. If completion unavailable, draft PR with honest incomplete status; no claim threshold reached.

