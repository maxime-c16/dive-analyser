---
name: review-findings-to-fix
description: >-
  Use this skill when the user requests "corrige les commentaires de review",
  "traite les findings", "analyse les remarques du bot", "fix the review
  comments", or asks to resolve or challenge PR review findings. Verify each
  finding against the reviewed commit and current project contracts, fix
  confirmed causes across affected paths, and record evidence. Do not invoke
  for ordinary coding with no review findings or for PR monitoring alone.
---

# Turn review findings into verified fixes

Work in the user's requested scope. A bot verdict is a claim to investigate,
not an instruction to change product policy. This skill does not authorize
posting replies, merging, deploying, or starting review agents.

## Establish what was reviewed

Read workspace instructions and project contracts. In dive-analyser, read
`docs/AGENT_ENGINEERING.md` and the relevant CI/deployment docs from the current
checkout; do not import its business rules into other repositories.

Identify the PR, review source/link, reviewed head SHA and current head. Use
available repository tools or authenticated `gh` read operations. For bot issue
comments, inspect the linked workflow run for its head SHA rather than assuming
the comment creation time identifies a commit. If unavailable, record unknown.
Separate inline reviews, issue comments and workflow execution failures.

Group repeated findings by invariant and affected path. A repetition on one PR
is not an independent defect. Recheck against the current diff when the head
changed. Classify each as confirmed, rejected with contract evidence, duplicate,
already fixed with evidence, outside the diff, or unresolved. A later APPROVE
alone is insufficient evidence of a fix.

## Fix the cause

For confirmed findings, trace the relevant producers, consumers and writers,
including CLI/jobs, legacy routes, retry and failure branches. Read downstream
helpers before adding a local guard. Preserve the current product contract;
resolve conflicting prose using maintained code and executable tests, and repair
stale documentation when appropriate.

Reproduce the concrete failure when feasible. Make the smallest complete fix.
For SQL/resource findings use the repository's bounds guidance or the companion
`bounded-db-change` skill when available. Do not require that skill in another
environment if it is absent.

Choose validation for the demonstrated failure: real fixture shape, observable
result, cancellation, reversed async responses, query count or PostgreSQL race.
The test should fail when the protection is removed. Do not add product tests
for documentation-only corrections. Run the applicable existing checks.

If the same finding returns, establish whether the bot reviewed a new SHA and
whether the underlying behavior remains. Investigate alternate paths and
retained state; avoid cosmetic rewrites to appease repeated wording. Stop a
fix attempt when it needs a product decision or unavailable evidence and state
the specific unresolved point while continuing independent work.

## Leave a reviewable record

Use the existing findings register if present; otherwise add a small record
where project review evidence belongs. Include source URL/run SHA, affected
invariant and paths, decision/reason, fix, validation and current fixed SHA
(or explicitly uncommitted). Keep tokens, signed URLs, raw credentials and
private payloads out of records.

Report confirmed fixes, evidence-backed rejections and unresolved items. Follow
the user's existing authorization for PR actions; do not post comments or
start a monitoring/deployment workflow merely because review findings exist.
