# Technique History implementation status

Status: incomplete foundation; **not the approved MVP**. Do not deploy or announce
this branch as Technique History. The approved proposal is preserved alongside
this document without product-scope amendments.

Implemented so far:

- A pure attribution resolver with exact-code precedence, explicit supported
  families, context constraints, blocking gaps, approximate boundaries,
  half-open immutable timestamp/ID ordering, ambiguity rejection, independent
  tracks, and explicit attempt over session over inferred precedence.
- Exact-context comparison validation and recorded comparison membership over
  the union of two episode intervals. Conflicting recorded assignments stay on
  their recorded identity side; gaps and subsequent recurrence are excluded.
  Same-identity pairs require a separate recorded-by-episode implementation.
- Draft SQLAlchemy storage models for tracks, identities, episodes, attempt
  assignments and revisions. They are deliberately not imported by the runtime
  model registry. These models are not a finished schema contract.

Not implemented: production schema/migration, immutable attempt key producers,
SQL attribution/aggregates, session flag persistence, ownership-safe APIs,
shared writer locks and previews, copy/edit/delete/undo mutations, Scores UI,
localization, segmented charts, pagination, modifier-set selectors, coverage
headers, accessibility interactions, ownership-change fencing and release note.
No frontend change or user-visible behavior is delivered. There is no product
contract conflict; these are outstanding implementation tasks.

## Resource contract to implement

These are design targets, not measured guarantees of an implemented API:

- Episode and attempt detail: keyset pages of at most 50 records plus one
  continuation sentinel; deterministic timestamp/ID cursors. Response <= 256 KiB.
- Mutation: at most 100 attempts or 16 copied scopes per transaction. Reject
  oversized requests before loading records; larger operations use explicit
  batches. Notes <= 2,000 characters, identity labels <= 120 characters.
- Preview and commit: lock the diver ownership row followed by the track row,
  re-read permissions and shared revision, then validate every affected scope.
  Family and exact-code writers use the same lock and revision. Reject stale
  previews with a conflict; never silently rebase a mutation.
- Read endpoints: target <= 12 SQL statements independent of attempts/history
  volume, <= 512 materialized rows, <= 2 MiB retained detail data. SQL execution
  may scan the complete indexed eligible history. No rating aggregate may be
  derived from a capped detail list.
- Comparison: complete SQL aggregates with continuous percentile median/IQR;
  equal-session mode first aggregates context-specific session subsets. Return
  at most two summary sides and bounded exact modifier sets with explicit
  pagination if the set inventory grows. Coverage precedes numerical ratings.
- No frontend cache until viewer/context/track/revision keys and request
  generation guards are integrated.

The pure resolver currently accepts a caller-provided list. It is suitable for
bounded preview rules and tests; loading all history to feed it in a production
endpoint would violate the approved resource contract. SQL resolution must be
implemented before API integration.

## Validation evidence

On 2026-11-09, the cached backend CI virtual environment ran:

`python -m pytest backend/tests/test_technique_history_rules.py -q`

Result: **8 passed**, 10 existing Pydantic deprecation warnings. The system
Python attempt failed during conftest import because SQLAlchemy was absent;
using the cached CI environment resolved that environment issue.

These tests prove the pure rules only. They do not validate PostgreSQL locks,
SQL statistics, access enforcement, migration, frontend rendering, accessibility,
caption resync or the complete feature. No complete CI tier has been claimed.

## Migration and backout

There is no migration ready to apply. Do not create production tables from the
draft models. The eventual additive SQL migration must run manually **before**
the dependent backend/frontend deploy; ship.sh does not apply SQL migrations.
It must backfill immutable occurrence keys once, establish creation defaults for
all ingest writers, and preserve keys across display-date edits and anchor
removal. All existing writer paths need regression coverage first.

A later application rollback should retain additive history tables and keys.
Never drop history as part of rollback. Stop dependent application writers before
any schema backout; preserve an independent backup and audit revisions. The
unintegrated foundation here requires no deployment or database action.

## Local commits

Foundation commit: `acd958e4` (approved proposal, resolver, draft models and
focused tests). This documentation follow-up records that immutable commit ID.
