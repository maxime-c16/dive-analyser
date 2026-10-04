# Selective Media Recall

## Resolver Order

1. Valid source-vault record for the canonical UUID.
2. Direct local path for the agent-local Photos UUID.
3. Exact safe local override.
4. Bounded one-UUID Photos materialization.
5. Structured unavailable result.

The recall manifest is read-only and bounded. It is primary-diver scoped and
creates neither jobs nor downloads. Explicit user preparation and new
captioned clips outrank representative and historical backlog work.

## One-Asset Recall

Use only the local UUID supplied in a lease. The approved automated command is
constructed as an argv list:

```text
osxphotos export <incoming>/<canonical-uuid>
  --uuid <agent-local-uuid>
  --only-movies
  --download-missing
  --update
  --verbose
```

Reject empty/invalid UUIDs, symlinks, tiny placeholders, files outside the
configured directory, invalid video streams, zero duration, and files above
the configured size limit. When multiple candidates exist, inspect all and
select the largest valid video after excluding placeholders.

## Batch Policy

- Batch 0: three known working, one permission-related, up to three placeholder samples.
- Later batches require a saved manifest, hard UUID limit, byte estimate, and
  free-space gate.
- Poster precedes proxy. A failed poster does not automatically create proxy.
- Never begin a historical batch while another is active.

Permission failures are operational and retryable once after access is fixed.
Placeholder-only exports are asset-specific and replacement-oriented.

