# Media Source Vault

## Permanent Layout

```text
/Volumes/DiveSenseiMedia/
  recalled_sources/by_uuid/
  recalled_sources/manifests/
  incoming/
  media_tmp/
  failed_diagnostics/
  state/
  checksums/
  logs/
  backups/
```

The volume must be APFS, writable, preferably at least 500 GB, and identified
by an expected volume UUID. A matching mount path alone is insufficient.

Each UUID directory contains one validated source and `source.json` with UUID,
kind, size, SHA-256, volume UUID, retention class, and validation time. The
registry on Debian records metadata but ordinary browser APIs do not expose
local paths.

## Thresholds

- Internal: warn below 30 GiB, pause historical recall below 22 GiB, stop
  nonessential media below 15 GiB.
- External: warn below 20%, pause recall below 15%, evict eligible temporary
  sources below 10%, stop media below 5%.

## Retention

- `permanent_representative` and `pinned`: retained.
- `recent`: default 60 days.
- `temporary`: eligible 24 hours after poster/proxy finalization.
- `failed_diagnostic`: 24-72 hours.

Cleanup supports dry-run, stays within the validated root, refuses symlinks,
and skips active, pinned, permanent, and manual-override sources.

