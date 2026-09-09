# MEDIA_BACKBONE_SECURITY_V1 — Storage Security Design & B2 Europe Research

Task packet: `MEDIA_BACKBONE_P0_P1_V1`. Research freshness: 2026-09-09.

## Security review (P1 design commitments)

| Control | Decision | Evidence / mechanism |
|---|---|---|
| Bucket privacy | **Private only.** Public buckets are out of scope; the adapter assumes and requires a private bucket. Reads happen in-process; future athlete delivery goes through short-TTL presigned GETs. | `B2Config` / adapter docs; no anonymous-read configuration surface exists |
| Least-privilege key | Use a **B2 application key** scoped to the single bucket (`capabilities: listFiles,readFiles,writeFiles` on the DEV bucket), never the master key. Master-key use is explicitly warned against in Backblaze's S3-API docs. | docs/architecture notes; operational provisioning step at DEV gate |
| DEV/PROD separation | Separate buckets by naming convention enforced by the config firewall: `diveanalyzer-dev-media` / `diveanalyzer-prod-media`; DEV-with-PROD-bucket (and vice versa) is a construction-time error. Tests cover both cross-wirings. | `mac-agent/src/ingest/objectstore/b2.py`, `test_ingest_backbone.py::TestB2ConfigFirewall` |
| Secrets | Server-side/agent-side only: `B2_APPLICATION_KEY_ID` / `B2_APPLICATION_KEY` environment variables (or operator-injected config). No credentials in source, fixtures, tests, or YAML examples. No browser exposure: the browser never talks to B2 in this packet. | env-var resolution in `B2Config.resolve_credentials()`; repo grep = zero hardcoded secrets |
| Presigned URLs | Bearer semantics: anyone with the URL can GET for the TTL. Short TTL default 3600s, hard max 7d (B2/S3 limit), validated at config and call time. Future P5 delivery must use per-request, per-object, minimal-TTL URLs. | `presign_get` validation + `MAX_TTL_SECONDS` |
| Logging | Never log credentials or presigned URLs. Structured ingest evidence is limited to: clip logical id, Photos source identity, ingest state, media SHA, caption SHA, object key, verification state, retry count, error family, temp path (coordinator state history). Caption raw text is persisted in `caption_revisions` (DB, private) but NOT in logs; parity harness reports hashes/lengths only. | `compare_caption_providers` redaction test; state history fields |
| Object keys | `blobs/sha256/<2>/<sha>` — no athlete name, no caption, no dive code, no email, no Photos title, no PII. Prefix charset validated. | `object_key_for_sha` + tests |
| Object metadata | No canonical caption/business state in object metadata; DB remains business authority. | TARGET doc; commit service |
| No destructive automation | `delete_object_explicit_operator_action` exists on the store adapter only, is unreachable from ingest/sync code, and no automatic purge is implemented. | grep: zero callers in ingest paths |
| No Cloudflare in V1 | Not included (per packet). | — |
| No Object Lock | Not enabled. | — |
| Science firewall | Object-store backbone handles application (athlete-visible) media only; no intersection with HQ analysis-source corpus, frozen D5/Event Logic artifacts. | CURRENT_STATE doc |

## Threat notes (explicit reasoning)

1. **Presigned URL leakage** → future P5: generate on demand server-side, TTL
   ≤ minutes for athlete playback, single object per URL, never cache in HTML
   longer than TTL, never log. V1 has no presign-consuming endpoint at all.
2. **Permanent credentials on iPhone** → none: the iPhone only feeds Apple
   Photos; no app-level cloud credentials are provisioned to devices in this
   architecture.
3. **Metadata transfer to US** (see EU research below): account/billing/API-key
   metadata is processed by Backblaze's US infrastructure even for EU-Central
   buckets. Object keys must therefore stay PII-free (already enforced).
4. **Environment cross-wiring** → enforced at construction (firewall) and at
   config validation (agent `Config.validate`); static guard test on the SQL
   migration prevents non-additive drift.

## B2 Europe region / account research (2026-09-09)

Primary sources: Backblaze docs (`backblaze.com/docs/cloud-storage-data-regions`,
`cloud-storage-call-the-s3-compatible-api`), Backblaze 2019 Amsterdam
announcement, and third-party analysis (sota.io, 2026-05) for the legal
dimension. No resources were created during this research.

### Operational facts

- **Available regions** (current docs): US West (Sacramento/Stockton/Phoenix),
  US East (Reston, VA), **EU Central (Amsterdam, Netherlands)**, Canada East
  (Toronto).
- **Region is ACCOUNT-LEVEL, chosen at account creation, and cannot be changed
  afterward.** Backblaze docs: "When you create a Backblaze B2 account, you
  choose whether that account's data is stored in the US East region, the US
  West region, the EU Central region, or the Canada East region… After you
  create your Backblaze B2 account, you cannot change your selected region."
  The S3-API docs confirm: "a Backblaze B2 account is associated with a single
  region. It is not currently possible to create buckets outside of an
  account's region." (Bucket-level region selection has been on Backblaze's
  roadmap since 2019 but is still not what the docs ship today.)
- **An account cannot span regions.** Multi-region is achieved with separate
  accounts administered together via Backblaze Groups.
- **EU Central endpoint:** `https://s3.eu-central-003.backblazeb2.com`
  (S3-compatible; boto3/AWS CLI/rclone work with endpoint + key substitution).
  HTTPS only.
- **EU data residency implications (operational):** customer object data
  uploaded to an EU-Central bucket stays in Amsterdam unless the customer moves
  it; account metadata (email, API keys, usage/billing) resides in US systems.
  Backblaze states restores/snapshots of EU data are served from Europe.
- **Migration difficulty if the region choice changes later:** no in-place
  region moves and no intra-Backblaze data move; migration = new account in the
  desired region + re-upload (or bucket replication rules between accounts in a
  Group — no replication egress fees). For this project the migration path is
  trivial-by-design: content-addressed blobs can be re-uploaded from the
  agent/vault or re-fetched from the old bucket, since the DB (not the object
  store) is the authority. Bucket/key format is region-independent.
- **Cost:** B2 is priced ~$0.006/GB/month storage and ~$0.01/GB egress
  (third-party 2026 reference; confirm exact numbers at account creation —
  pricing is outside this packet's authority). EU Central launched Q1 2023 with
  the same B2 pricing as US regions; no EU price premium documented.
- **Operational constraints:** S3-compatible API only (no B2-native key
  required); master application key cannot be used with the S3 API — create a
  bucket-scoped application key; multipart upload ETags are not SHA-256
  equivalent (already handled: our integrity identity is SHA-256, tested).

### Legal/policy dimension — FLAGGED AS HUMAN DECISION, not resolved here

- Backblaze, Inc. is a US (California) corporation; US law (including the
  CLOUD Act) applies to the provider relationship regardless of the Amsterdam
  data center. Third-party 2026 analysis argues EU-Central provides data
  *residency*, not legal *sovereignty*; SCC-based DPA exists but its adequacy
  under Schrems II reasoning is a legal judgment.
- **No GDPR/compliance claim is made or guessed in this document.** Whether
  EU-Central residency is sufficient for this deployment's personal-data
  posture (single-athlete training media, LAN distribution) is a human/legal
  decision. Evidence-backed alternative if sovereignty is required: EU-based
  providers with EU legal entities (e.g., Hetzner Object Storage,
  OVHcloud) — also S3-compatible, i.e., our `ObjectStore` port makes this a
  configuration change, not a rewrite.

### Recommended setup for European athlete media (operational recommendation, legal sign-off human)

```text
Account layout (at DEV/PROD provisioning gate, NOT created in this packet):
  Option A (single-region EU): one EU-Central account
    bucket diveanalyzer-dev-media  (private, bucket key w/ write+read)
    bucket diveanalyzer-prod-media (private, bucket key w/ write+read)
  Option B (strict DEV/PROD isolation): two EU-Central accounts (one per env),
  administered via Backblaze Groups
DEV first, canary on DEV bucket only; PROD created only at the P4 gate.
```

Both options keep DEV and PROD in separate buckets; Option B additionally
separates credentials/accounts, which matches the packet's environment
separation doctrine more strictly and is therefore the recommended shape if
both buckets are provisioned by the same provider account holder.

## B2 resource plan (proposed, NOT executed)

| Item | Value |
|---|---|
| DEV bucket | `diveanalyzer-dev-media` — private, EU-Central region (pending human region decision) |
| PROD bucket | `diveanalyzer-prod-media` — private, created only at P4 gate |
| DEV app key | bucket-scoped application key (files read/write/list on DEV bucket only) |
| PROD app key | bucket-scoped, separate, provisioned at P4 |
| Secrets transport | environment variables on the mac-server agent runtime + backend env; never in Git |
| Object prefix | `blobs/sha256/` |
| Endpoint | `https://s3.eu-central-003.backblazeb2.com` (if EU Central selected) |
