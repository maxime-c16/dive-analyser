---
name: bounded-db-change
description: >-
  Use this skill when the user requests "corrige les N+1", "borne les
  requêtes", "optimise cette agrégation", "évite de tout charger en mémoire",
  "fix unbounded queries", or asks to implement or review database lists,
  rankings, inventories or workers with growing data volumes. Bound database
  work and retained memory while preserving complete statistics and explicit
  pagination. Do not invoke for unrelated SQL syntax questions or ordinary
  small CRUD changes without a volume or query-budget concern.
---

# Bound work while preserving results

Read project conventions and the production database/runtime constraints.
In dive-analyser, use `docs/AGENT_ENGINEERING.md` and `ci/README.md` in the
current checkout. Do not assume its single-worker topology in other projects.

## Define the result and its cost

Identify the logical entities and growing dimensions: accounts, aliases,
history, versions, recipients, queued jobs. Distinguish four costs: rows
materialized, SQL round trips, retained memory and response size. State which
are bounded by a page/batch and which must cover the whole eligible scope.
A time window does not cap the number of entities; a bounded parent set does
not cap its children or history.

Choose SQL aggregation/ranking/existence checks for full-scope answers and
bounded detail fetches for display. Use stable, unique ordering and matching
cursors. If a complete inventory must scan all rows, make that cost explicit
and process bounded resumable batches; do not promise constant total work.
Streaming only bounds memory if accumulators and downstream helpers are bounded.

## Inspect the entire path

Check lazy relationships, per-item `refresh`/commit, nested helpers, retry
paths, negative lookup fallbacks and expanded `IN` lists. Prefetch or use SQL
subqueries for the selected batch. Include zero/missing values in prefetched
maps so absence does not trigger N additional queries.

For ambiguity checks, select distinct entity IDs before applying the limit.
Joined alias rows and ORM `.unique()` do not provide that guarantee. A limit
of two entities can prove uniqueness; two joined rows cannot.

Do not hide incomplete answers behind arbitrary page caps. Return a cursor,
explicit partial status or a server aggregate as appropriate. Workers must
persist progress or otherwise ensure later candidates are eventually examined;
a fixed first page can starve valid work behind rejected items.

For resource queues and streams, apply capacity limits before allocating,
parsing or writing. Track backpressure and continuation rather than silently
dropping excess jobs or recipients. Inspect the actual framework boundary.

## Validate the chosen invariant

Use the smallest representative tests: multiple aliases per entity, many
historical versions of one parent, tied cursor keys, missing prefetched rows,
volume growth, rejected early candidates or full-scope statistics beyond page
one. Measure SQL round trips for the complete response where N+1 is the risk;
assert the observable result as well as the budget.

Use the production dialect for SQL, lock and savepoint behavior that SQLite
cannot prove. Keep test databases isolated. Do not impose a global `.all()`
ban: a proven bounded query may safely materialize a small result.

Report the result contract, selected bounds, residual full-scope work,
validation and any change to pagination/API behavior. Follow the project's
release-note and deployment contracts if product behavior changes.
