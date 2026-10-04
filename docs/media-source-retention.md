# Media Source Retention

- `permanent_representative`: active representative or explicitly pinned;
  never automatically evicted; budget 8 GiB.
- `recent`: newly detected captioned videos; retained 30 days by default;
  budget 8 GiB.
- `temporary`: historical recall and one-off Prepare; eligible 24 hours after
  poster and proxy are finalized and verified; budget 3 GiB.
- `failed_diagnostic`: retained 24 hours by default.
- `quarantine`: invalid stream, checksum, type, path, or suspicious source;
  never reused; retained 24 hours.

Eviction order is quarantine, diagnostics, completed temporary, expired recent,
then oldest finalized unpinned recent data under quota pressure. Active,
incomplete, pinned, permanent, unverified, symlinked, off-volume, and
out-of-root files are protected.
