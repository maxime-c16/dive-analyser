# Engineering checks for agents

Read this before changing code. Apply only the sections touched by the change.
Evidence and historical examples: [review-bot patterns](reviews/REVIEW_BOT_PATTERNS.md).
Deployment authority: [repository workflow](REPO_WORKFLOW.md). Validation:
[CI matrix](../ci/README.md). Do not copy historical findings into new rules
without checking current code and executable tests.

## Before implementation

State the invariant and identify its producers, consumers and writers. Include
API variants, legacy paths, CLI/bootstrap, scheduled jobs and retries. Check
current contracts when a role name, `ready` state or feature flag is ambiguous.
Friend/diver role does not prohibit ownership-scoped dive writes; operational
permissions remain separate. Use `write_guard.py`, `dive_access.py` and the
access tests rather than inferring permissions from a role label.

## SQL, queues and resource budgets

- Bound rows fetched, query count, retained memory and response size separately.
  A paged response, time window or `yield_per` does not bound all four.
- Aggregate/rank/filter in SQL before materializing rows. Fetch details only
  for the selected page or ranked candidates; bulk-load associations and
  ensure zero/missing entries do not trigger per-item fallback queries.
- Limit distinct entity IDs before loading joined rows. In ambiguity checks,
  multiple aliases of one entity must not hide a second entity.
- Keep full-scope counts/statistics correct. Expose pagination or continuation;
  never silently call a capped partial list complete. Workers need bounded
  scans and progress so rejected early candidates cannot starve later ones.
- Enforce byte/disk/concurrency budgets before consumption, including framework
  multipart parsing and old routes. Bound streaming reads and deadlines;
  cancel rejected response bodies and clean staging on errors/cancellation.
- On the single uvicorn worker, trace synchronous ORM/network/file work through
  helpers and background tasks. Use an appropriate threadpool/session boundary
  or durable worker; `async def` alone does not offload blocking operations.

## Identity and asynchronous state

- Scope cached private results by viewer and every result-changing filter or
  permission dimension. Reset on identity changes and invalidate in-flight work.
- Guard render state and success/error/finally updates by current request or
  generation. Cover selection/filter changes, logout, quit and retries.
- Routes returning signed playback URLs must authorize the underlying media,
  including status/batch/preview paths. Public UUIDs are not capabilities.
- Use semantic state, not translated strings, for branching. Preserve absent
  versus zero, fallback versus target-ready, and shared metric definitions.

## Atomicity and secrets

- All writers must follow the same lock/constraint protocol. Read decisive state
  under the lock, refresh stale ORM objects, then revalidate and mutate.
- Handle uniqueness conflicts and roll back failed sessions before continuing.
  Use PostgreSQL for production-specific locks, SQL and savepoint behavior.
- Fence source changes during file generation/publication. Clean losing or
  cancelled outputs; account for orphan bytes and deletion grace periods.
  SQL rollback cannot restore deleted files. Never delete the sole safe copy.
- Do not forward session credentials across redirect origins. Sanitize exception
  causes, SQL parameters, signed URLs and proof artifacts as well as messages.
  Secret capabilities require independent unpredictable entropy.

## Verification and review handoff

Choose the smallest meaningful checks from the CI matrix. Use real data shapes;
assert observable behavior, cancellation and failure recovery, not only that a
mock was called. A proof should fail if its protection is removed. Check actual
redirect destinations and media bytes where those are the claimed property.
Docs-only changes need no product test suite.

Use [the findings register](reviews/REVIEW_FINDINGS.md) for review evidence.
For each bot finding record: source/run SHA, affected invariant, confirmed or
rejected with evidence, all affected paths, minimal fix, and validation. Group
repeated wording on one PR; do not count each run as an independent defect.
If the same finding returns, inspect the downstream helper, alternate writer,
error/retry branch or retained state before adding another local guard.
A green review workflow means execution completed; inspect its verdict and
findings separately. Historical approval is not approval of a newer head.

For deployment-related changes, document migration order, injected flags,
proxy recreate/reload, Mac worker and timers using REPO_WORKFLOW.md. Verify
service-level state and rollback dependencies. Add immutable user-visible
release notes listing all required services when applicable.
