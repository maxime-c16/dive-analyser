# Media Source Vault

## Internal Working-Set Layout

```text
/Users/Shared/services/data/media-node/
  sources/by_uuid/
  manifests/
  incoming/
  media_tmp/
  failed_diagnostics/
  state/
  checksums/
  quarantine/
```

The root must be writable and backed by Data volume UUID
`68C4DD7B-F527-46DE-8481-5D01F49F21DA`. A matching path prefix alone is
insufficient.

Each UUID directory contains one validated source and `source.json` with UUID,
kind, size, SHA-256, volume UUID, retention class, and validation time. The
registry on Debian records metadata but ordinary browser APIs do not expose
local paths.

## Thresholds

- Warning below 35 GiB free.
- Pause historical recall below 30 GiB.
- Pause automatic source recall below 24 GiB.
- Stop processing below 18 GiB.
- Managed source quota: 20 GiB, hard configurable ceiling 25 GiB.
- Per-class budgets: permanent 8 GiB, recent 8 GiB, temporary 3 GiB,
  diagnostics/quarantine 1 GiB.
- Automatic source maximum: 1 GiB. Hard single-source maximum: 2 GiB.

## Retention

- `permanent_representative` and `pinned`: retained.
- `recent`: default 30 days, configurable from 14 to 60 days.
- `temporary`: eligible 24 hours after poster/proxy finalization.
- `failed_diagnostic`: 24-72 hours.

Cleanup order is expired quarantine, diagnostics, completed temporary, then
recent sources. It supports dry-run and removes at most 20 items or 5 GiB per
pass. It stays within the validated root, refuses symlinks, and skips active,
incomplete, pinned, permanent, and unverified sources.
