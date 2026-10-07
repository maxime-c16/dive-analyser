# Automatic community reviews

The daily selection is the default entry in Evaluations. Public attributed
videos with an active current OWNER account participate unless excluded in
Community scores. Private dives never enter this transport. Public visibility
was historically the default: the UI explicitly explains automatic inclusion
and offers per-dive exclusions; review existing public visibility before rollout.

Selections contain up to three playable dives and may be partial or empty.
Each current owner account gets its first candidate before a second candidate
from any owner; candidates within an owner prioritize fewer automatic votes,
then recent dives, then ID. An SQL window rank avoids a large uploader starving
smaller libraries. Shared-owner bindings use the lowest active owner account ID
for distribution; every binding is respected for self-review exclusion.

Daily selections are created lazily on the first POST and keyed by UTC date.
On-demand selections use a client UUID. Both are stored transactionally;
PostgreSQL serializes allocations per reviewer. They do not reserve media from
other reviewers. An unconsumed selection excludes its items from other
selections for 24 hours. Skips cool down seven days; submitted automatic votes
exclude a dive permanently for that account. Daily retries do not replace
items, including an empty selection. Returning to a stack revalidates all
items. Media warm-up is limited to three unavailable candidates per new stack
POST and uses the existing idempotent media job preparation; GETs create no jobs.

Automatic votes have their own table and unique (dive, reviewer) identity.
Manual evaluation votes are unchanged; an account may independently submit one
vote in each channel. Ratings snapshot video identity and dive context. Votes
and scores never overwrite official scores, DD or analytics. Community scores
are per dive, count distinct reviewers, and are always labelled experimental
and provisional. There is no cross-diver leaderboard. A mean alone cannot
correct reviewer severity, collusion, footage quality or sparse coverage.

All automatic endpoints require active browser authentication and mutation
origin checks. Media URLs remain authenticated and are reauthorized on every
request. No private notes or download URLs enter a stack. Visibility, exclusions,
owner binding/activity and self-review are checked again on votes and media.
Owner exclusions and votes lock the dive row on PostgreSQL. Exclusions retain
historical votes; deletion of a dive cascades its automatic records.

## Deploy

Apply `backend/migrations/add_automatic_reviews.sql` against server PostgreSQL
before `ci/ship.sh server` (after its required dry run). The SQL is additive and
idempotent. Missing tables return 503 from automatic endpoints, leaving manual
evaluations available. No Mac worker code changes are required. App rollback
can leave these additive tables in place.

## Validation

API integration tests cover public/private/self/foreign access, daily and
on-demand retry identity, skips, votes and immutable retries, independent manual
votes, withdrawal and disabled owners. Frontend tests cover automatic routing,
finite stacks, resumption and opt-out controls; the existing jury state-machine
suite continues to exercise the shared immersive stage.

Public dives attributed to a diver without an OWNER account are eligible. Unattributed dives and dives bound only to inactive accounts remain excluded. Fairness uses the active owner account, falling back to the individual diver until binding. Ownership is rechecked on queue, media and vote requests. Historical automatic votes remain immutable; votes by a current owner are excluded from community aggregates and selection priorities, including votes submitted before account binding.

Automatic playback can use the verified original backbone through the existing authenticated playback route after checking automatic-review eligibility. Cached 720p/original remains available; proxy-only clips trigger preparation and the player polls for HQ for up to 90 seconds. The normal playback route continues to enforce storage integrity and authorization.
