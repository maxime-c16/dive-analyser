# Degree of Difficulty

DiveSensei calculates degree of difficulty (DD) from the component formula in
the FFN French edition of the World Aquatics Diving Rules, 2022-2025,
Appendices 1-3. The implementation identifier is
`ffn_world_aquatics_diving_2022_2025_appendix_1_3`.

Source: [FFN / World Aquatics Diving Rules 2022-2025](https://www.ffnatation.fr/sites/default/files/2023-10/FFN-WA-PL-2023-2025.pdf), Appendices 1-3.

## Rules in the product

- DD is calculated from the canonical dive code and the board height, not from a
  hand-maintained lookup table or a heuristic.
- `7m` is normalized to the official `7.5m` table and the historic application
  alias `3mp` is normalized to `3m`.
- Straight jumps and code/position combinations not defined by the rulebook are
  explicitly `not defined`; they never receive an estimated DD.
- Existing `dives.official_dd` values are a materialized audit/cache field.
  `official_dd_source` records the rulebook version and
  `official_dd_verification_status=official_formula` records successful
  reconciliation.
- The live DD workspace uses the formula directly, so it remains accurate while
  a reconciliation is being inspected.

## Analytics interpretation

- Execution remains the primary athlete-facing score on its calibrated `0–10`
  scale. Per-dive progression charts therefore remain execution-only.
- Mixed-dive aggregate views also expose **DD-adjusted execution**:
  `rounded execution score × official DD`. It provides a descriptive index for
  comparing a training block that contains different dive difficulties.
- The index is not an official competition total. Competition scoring requires
  the applicable panel scores, deductions, and event rules.
- Every aggregate reports DD coverage. Do not compare DD-adjusted values as a
  complete population when coverage is materially below 100%.
- Success rate stays on its raw, visible performance threshold. DiveSensei does
  not manufacture a DD-adjusted success threshold.

## Reconciliation

Run a dry run first:

```bash
docker-compose exec -T backend python scripts/reconcile_official_dd.py
```

After a PostgreSQL backup and review of the dry-run counts:

```bash
docker-compose exec -T backend python scripts/reconcile_official_dd.py --execute --batch-size 200
```

The migration `backend/migrations/add_official_dd_provenance.sql` must be
applied before execution. The migration is additive; rollback consists of
restoring the pre-reconciliation database backup, not deleting dive records.

## Rulebook updates

The calculation is deliberately versioned. Before adopting a newer World
Aquatics/FFN edition, compare every formula component and table row, extend the
reference tests, then update the reference ID and re-run reconciliation.
