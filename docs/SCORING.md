# Scoring contract

Every number the app calls a "score" or a "note" is listed here. Read this
before touching any score, average, success rate, colour band or ranking.
If a change needs a new rule, add it here in the same PR.

## The rule in one line

There are two notes, and they are never mixed: the **note perso** (the
diver's own letters) and the **note du jury** (other members' votes). Each
screen shows one of them, labelled as such.

## 1. Note perso — the diver's letters

Source: Photos captions (`mac-agent/src/metadata.py`) or the clip editor
(`PUT /api/v1/dives/{id}`). Stored on `dives`.

| Letter | Meaning | 0–10 score | Band (score ≥) | Ordinal (`performance_numeric`) |
|---|---|---|---|---|
| P | Parfait | 10 | 8.5 | 4 |
| G | Bon | 7 | 5.75 | 3 |
| M | Moyen | 4.5 | 3.25 | 2 |
| B | Non satisfaisant | 2 | 1 | 1 |
| F | Manqué | 0 | 0 | 0 |

Names follow the FFN / World Aquatics judging bands (one name per letter,
`performance.*` and `dives.ratingsScale` in the locales).

- **Single rating**: `performance` holds the letter; the score is its 0–10 value.
- **Two phases**: `phase1_performance` (hurdle + flight) and
  `phase2_performance` (opening + entry). Score = `0.45 × phase1 + 0.55 × phase2`.
  The stored `performance` letter is the **band of that score** (nearest
  letter), e.g. G + P = 8.65 → P; P + M = 6.975 → G; F + P = 5.5 → M.
- The score is the authority. The letter, its colour and every success count
  derive from it, so they cannot disagree.
- The 0–4 ordinal is legacy (constraints, index); never display it.

Owners — change these together; `backend/tests/test_scoring_contract.py` fails
if they drift:

- `backend/app/services/performance_scoring.py` — `ATHLETE_SCORE_10`,
  `PHASE1_WEIGHT`/`PHASE2_WEIGHT`, `GRADE_FLOORS`, `grade_for_score`,
  `composite_grade`, `dive_score_10`, SQL `recorded_score_10_expression`.
- `backend/app/services/phase_validator.py` — `infer_legacy_score` (calls
  `composite_grade`; used by Photos sync and the clip editor).
- `frontend/src/utils/performanceScoring.ts` — the same constants,
  `gradeForScore`, colour helpers. `codeStats.scoreBand` is an alias.
- `backend/migrations/backfill_two_phase_composite_grade.sql` — realigns rows
  written under the old `min(phase1, phase2)` rule.

### Derived metrics

| Label (fr / en) | Definition | Function |
|---|---|---|
| Réussite / Success | letter M or better (score ≥ 3.25) | `is_success`, `isSuccessfulPerformance` |
| G ou mieux / G or better | letter G or P (score ≥ 5.75) | `is_excellent`, `code_summaries.SUCCESS_SCORE` |
| Analyse détaillée "Réussite · seuil X" | letter X or better; the threshold is shown | `dive_analysis_service.summarize` |
| Performance moyenne | mean of 0–10 scores (Sessions, Dashboard, Analytics) | `dive_score_10` |
| Médiane | median of 0–10 scores (code cards, code analysis, leaderboard, community) | `code_summaries`, `codeStats.median` |

Do not label a G‑or‑better rate "Réussite". Show a mean and a median under
different labels; never swap one for the other on the same metric.

Straight jumps (codes starting 100/200/300/400) are excluded from analytics
(`is_analytics_dive`). Lineup dives are excluded from personal stats.

Colours: green = G band or above, amber = M band, red = below M
(`performanceColor`, `performanceBorder`, `performanceBarColor`). Do not
hard-code thresholds in components.

## 2. Note du jury — other members' votes

Votes are integers in **half steps** (`score_half_steps`, 0–20 → 0–10 by 0.5).

| Circuit | Table | Opened by |
|---|---|---|
| Request (jury) | `evaluation_ratings` via `evaluation_requests` | the owner asks for an evaluation |
| Automatic (community) | `automatic_ratings` | public dive with ready media |
| Judge room (game) | `judge_room_ratings` | live room; feeds the game only, ghosts never count |

`dive_evaluation.context` picks one circuit per dive and viewer; a member
votes once per dive. Owners never vote on their own dives.

The displayed jury note is the mean of votes, one decimal. Known
divergences to fix (one shared aggregate is the target):

- `matchmaking.results` excludes automatic votes cast by an account that
  now owns the dive (`community_vote_clause`); the other aggregates below
  do not.
- `dive_series.rating_totals` pools both circuits, drops votes whose code,
  height or video changed, rounds to 2 decimals, and does not apply
  `community_vote_clause`. Its "best" ordering falls back to the note perso
  when no vote exists — the two notes are compared as if they were one scale.
- `diver_score` pools both circuits without the stale-vote filter.

## 3. Composite indicators (not notes)

These are 0–100 indices. Never show them next to a 0–10 note as if comparable.

- **Score plongeur** (`services/diver_score.py`): account level.
  60 performance (mean received jury note × 6, damped below 5 votes) +
  25 judging (distinct dives judged, cap 10) + 15 community (likes and
  comments, cap 50). Provisional under 3 received votes.
- **Personal Dive Value** (`services/personal_dive_value.py`): one dive of the
  primary diver; review priority from technique × DD, same-dive percentile,
  breakthrough, progression, consistency, novelty. Not an official score.

## 4. Dead code — do not build on it

`services/performance_scorer.py` (7/11-judge FINA panel) and
`services/results_aggregator.py` (competition standings with a hard-coded
execution of 8.0) are only imported by `tests/test_fina_sprint*`. No route or
screen uses them.

## Checklist for a scoring change

1. Update the owner function, never a local copy in a component or query.
2. Update this file and `test_scoring_contract.py`.
3. If stored letters change, ship an idempotent backfill in
   `backend/migrations/` and add it to the table in `docs/REPO_WORKFLOW.md`.
4. Run `ci/gate.sh backend` and `ci/gate.sh frontend`.
