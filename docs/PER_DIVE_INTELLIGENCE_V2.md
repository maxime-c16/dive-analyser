# Per-Dive Intelligence V2

## Architecture

Per-Dive Intelligence is an attempt-traceable analytical layer over `dives`, `sessions`, `dive_modifiers`, `divers`, `training_periods`, and the media cache registry. The combined endpoint is `GET /api/v1/dive-analysis/{dive_code}`. Modular read endpoints expose attempts, phases, insights, breakdowns, and comparisons without changing the underlying calculations.

Every chart point contains a real `dives.id`. Opening it reads media status for that attempt's `video_uuid`; rendering a chart or table never creates a media job. `Prepare clip` remains the only browser action that requests `proxy_360p`.

## Filtering

- Dive codes are canonicalized to uppercase. Straight-jump families `100`, `200`, `300`, and `400` are rejected with `straight_jump_not_supported` and HTTP 422.
- `DB`, `SD`, and `HU` are normalized rows in `dive_modifiers`. `SYNC` is filtered through `dives.is_sync`, never as a modifier.
- `modifier_mode=any` requires at least one selected modifier; `all` requires every selected modifier; `none` requires no modifiers.
- `diver_ids` accepts one or more normalized diver IDs. The deprecated `diver` string remains temporarily available.
- `training_period_ids` selects attempts whose dates belong to any selected period. Overlapping periods are all returned on the attempt.
- Date-only `date_to` values include the entire day. Selected bounded periods are compared with the immediately preceding period of equal duration.

Examples:

```text
/dives/analysis/103B
/dives/analysis/103B?modifiers=DB&modifier_mode=all
/dives/analysis/103B?modifiers=DB&date_from=2026-04-10&date_to=2026-07-10
/dives/analysis/5122D?date_from=2026-04-10&date_to=2026-07-10
```

## Diver normalization

`divers` stores display and canonical names. Canonicalization trims whitespace, collapses repeated spaces, and case-folds. `diver_aliases` only merges an identity when an explicit exact alias exists; fuzzy matching is intentionally absent. `dives.person_name` remains untouched for compatibility.

Blank historical `person_name` values are assigned to the configured primary diver. Production uses `PRIMARY_DIVER_NAME=Maxime`. The migration is idempotent and only fills `dives.diver_id` when it is null.

## Training periods

Training periods are inclusive date ranges. Overlap is allowed and visible. Read access is available at `GET /api/v1/training-periods`; create, update, and delete require the existing `X-API-Key` protection. The migration seeds a `2026 Season` period idempotently.

## Scoring and weighting

The athlete-facing nonlinear 10-point scale remains:

```text
F=0.0, B=2.0, M=4.5, G=7.0, P=10.0
```

Two-phase attempts use `45% Phase 1 + 55% Phase 2`. A single rating uses that rating directly. Missing phase values stay missing and are never replaced by zero.

`weighting=attempts` gives each repetition equal influence. `weighting=sessions` first computes the median for each session and then summarizes those session medians. Raw attempt counts and source points remain available in both modes.

Success defaults to `G` or better and can be changed to `M`, `G`, or `P`. The active definition is always returned.

## Trend and interpretation safeguards

Trend requires at least five scored attempts across at least 14 days. Raw points remain visible beside a rolling five-attempt median. Descriptive sample labels are:

```text
0: no data
1-2: insufficient
3-5: exploratory
6-11: moderate sample
12+: stronger descriptive sample
```

Insights report observed median, spread, success, phase, and context changes. They never claim a drill, height, or training period caused an outcome.

## Query cache

Media-independent calculation results use `analytics_cache` with a 60-second default TTL. Keys include dive code, all filters, weighting, success threshold, period IDs, and analytics version. New/updated/deleted dives, modifier syncs, diver edits, and period edits invalidate V2 entries. Media status is assembled after the analytical cache lookup so clip readiness is not held for the cache TTL.

Responses include cache hit/miss, query duration, calculation duration, total duration, and result size. Captions are never written to cache logs.

## Deployment

1. Back up PostgreSQL and archive the current frontend.
2. Apply `backend/migrations/add_divers_and_training_periods.sql` once. It is safe to rerun.
3. Verify every existing dive has `diver_id`, the primary diver is unique, and `2026 Season` exists once.
4. Restart the backend, verify health and V1 endpoints, then stage/build the frontend.
5. Verify uncached and cached analysis requests, normalized filters, phase endpoints, and passive media-job count.

## Rollback

Restore the previous frontend image or archived static files first. Restore the previous backend image if analysis endpoints fail. Leave additive `divers`, `diver_aliases`, `training_periods`, and `dives.diver_id` in place; V1 code ignores them. Do not roll back or delete media infrastructure. The pre-V2 PostgreSQL dump is the last-resort data rollback.

## Known limitations

- Authentication is suitable only for LAN/WireGuard deployment.
- Aliases require manual creation; fuzzy identity merging is intentionally unsupported.
- Period membership is date-based rather than an explicit dive-period join.
- Comparison labels are descriptive, not statistical confidence claims.
- Computer-vision execution features, causal coaching, predictions, originals, `proxy_720p`, and bulk media warming remain deferred.
