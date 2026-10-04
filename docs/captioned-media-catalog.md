# Captioned Media Catalog

The catalog is a read-only inventory of captioned movies visible to one Mac
Photos agent. A run loads the Photos database once, uploads metadata in chunks
of 200, and checkpoints each accepted chunk on Debian. It never invokes export,
`--download-missing`, or the media-job API.

Each row preserves the agent-local UUID, cloud fingerprint, caption, capture
metadata, canonical production mapping, media readiness, source readiness,
eligibility, and exclusion reason. Ambiguous fingerprints, missing mappings,
invalid captions, hidden assets, straight jumps, and canonical-code mismatches
remain visible as excluded rows rather than disappearing.

Cataloging is allowed only with at least 22 GiB free. One active catalog run is
permitted; rerunning creates a new revision and idempotently updates rows keyed
by agent and local UUID.

Operator endpoints:

```text
POST /api/v1/media/catalog/runs
GET  /api/v1/media/catalog/runs/latest
GET  /api/v1/media/catalog/summary
GET  /api/v1/media/catalog/items
```

Chunk and completion endpoints require the allow-listed Mac agent API key.
