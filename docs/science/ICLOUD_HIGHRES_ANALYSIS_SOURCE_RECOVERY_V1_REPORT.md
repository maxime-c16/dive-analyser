# ICLOUD_HIGHRES_ANALYSIS_SOURCE_RECOVERY_V1_REPORT

**Date:** 2026-09-09  
**Repository:** `/Users/maximecauchy/.perso/diveanalyzer-perception`  
**Branch:** `uiux-overhaul-pro-app`  
**Starting media-thread HEAD:** `f49db5f03715c001b662aa27e8a0d870bcd9fa81`  
**Observed working HEAD before this report:** `484c00a7e157e227afea712d7adae7a661f3affc`  
**Status:** `RECOVERED_WITH_QUARANTINES`

## 1. TCC blocker history

The previous recovery attempt ended at `HIGHRES_RECOVERY_BLOCKED_TCC`: Photos catalog metadata and iCloud identities were visible, but full-byte PhotoKit materialization failed with `Error: could not get authorization to access Photos library`.

No high-resolution source was recovered in that run, and the earlier `ANALYSIS_SOURCE_HQ_V1_FREEZE.json` state was `NOT_FROZEN_CANARY_GATE_CLOSED`.

## 2. Exact TCC client

The exact client evidence is recorded in `docs/science/PHOTOS_TCC_CLIENT_V1.json`.

- Photos host: `mac-server.home` / `192.168.1.19`, user `divesensei`
- macOS: `15.1.1` build `24B91`, `x86_64`
- Photos library: `/Users/divesensei/Pictures/Photos Library.photoslibrary`
- Deployed agent: `com.diveanalyzer.agent`
- Authorized app wrapper: `/Users/divesensei/Applications/DiveSensei Python Runtime.app`
- Bundle id: `com.diveanalyzer.python-runtime`
- Runtime child: `/Users/Shared/services/data/diveanalyzer/venv/bin/python`
- osxphotos entrypoint: `/Users/Shared/services/data/diveanalyzer/venv/bin/osxphotos`

The direct SSH-launched venv Python remained denied after the UI grant. The successful client path was a one-shot Aqua LaunchAgent in the logged-in user session with `AssociatedBundleIdentifiers = com.diveanalyzer.python-runtime`.

## 3. Human authorization action

The maintainer granted Full Photos Access on `mac-server.home` to both visible entries: `DiveSensei Python Runtime` and `python3`.

No TCC database edits, SIP changes, Photos database mutations, or private iCloud APIs were used.

## 4. Full-byte iCloud proof

Dive 311 was used as the single full-byte canary before batch recovery.

- UUID: `D0C33293-F4B7-4A57-9368-9C53BFC32033`
- Photos materialized render: `/Users/divesensei/Pictures/Photos Library.photoslibrary/resources/renders/D/D0C33293-F4B7-4A57-9368-9C53BFC32033_2_0_a.mov`
- Exported edited HQ: `/Users/Shared/services/data/media-node/incoming/launchagent_probe_311/export/IMG_2156_edited.mov`
- Bytes: `7352846`
- SHA256: `9bcb37fa3bca5b044855b89e978d7cfe77a9cd3a162ebbb8792e38efb26050e5`
- Codec/resolution: `hevc`, `1920x1080`
- Duration/frames: `7.118345s`, `218`

Result: `ICLOUD_FULLBYTE_DOWNLOAD_PASS`.

## 5. Canary recovery

Planned canaries `133`, `311`, `676`, and `2169` were recovered one asset at a time through the authorized Aqua LaunchAgent path. All four produced ffprobe-readable edited HQ files and checksums.

Canary temporal gate:

- Passed: `133` (`PTS_EQUIVALENT`)
- Passed: `676` (`DETERMINISTICALLY_MAPPABLE`; visual contact sheet confirmed same content with crop/brightness transform)
- Passed: `2169` (`PTS_EQUIVALENT`)
- Failed: `311` (`NOT_EQUIVALENT`; HQ is 7.118s while current proxy is 19.267s)

Minimum gate passed: 3 successful recovered and aligned/mappable canaries.

## 6. Original master

For the canary set, `ORIGINAL_MASTER` was exported with `--skip-edited`. Empirically, osxphotos produced byte-identical files to the edited export for all four recovered canaries. This does not grant direct label-transfer authority to raw masters generally; it only records the observed behavior for this installed osxphotos/Photos state.

## 7. Edited high-res rendition

The scientific target is `EDITED_HIGHRES_RENDITION`, exported with:

`osxphotos export TARGET --uuid UUID --only-movies --download-missing --use-photokit --update --skip-original-if-edited`

This path preserves the Photos-exported rendition that the current app pipeline can request. It is the only candidate frozen as `ANALYSIS_SOURCE_HQ_V1`, with per-asset temporal authority.

## 8. Temporal alignment

Temporal alignment used ffprobe frame PTS sequences and ffmpeg-extracted start/middle/end frame fingerprints. Average FPS was not used as authority.

Batch result:

- `RECOVERED_ALIGNED`: 11
- `RECOVERED_DETERMINISTIC_MAPPING`: 1 (`676`)
- `TEMPORAL_MISMATCH_QUARANTINED`: 2 (`311`, `524`)

Label transfer is allowed only for `PTS_EQUIVALENT` and `DETERMINISTICALLY_MAPPABLE` assets. It is prohibited for `311` and `524`.

## 9. Source freeze

`docs/science/ANALYSIS_SOURCE_HQ_V1_FREEZE.json` now supersedes the prior blocked freeze and records `FROZEN_WITH_PER_ASSET_TEMPORAL_AUTHORITY`.

This is not a blanket claim that every recovered HQ file is timeline-compatible. The freeze is per asset, using `HIGHRES_ANALYSIS_SOURCE_MANIFEST_V1.json`.

## 10. Storage sizing

- Free before batch: `21994084 KiB` on `/System/Volumes/Data`, about 21 GiB
- Estimated original input bytes from Photos metadata: about 341 MiB
- Exported edited HQ bytes: `355637796`
- Temporary/canary retained bytes: 104 MiB
- Batch durable bytes: 341 MiB
- Free after batch: `21098440 KiB`, about 20 GiB
- Safety reserve: maintained above the configured 8 GiB warning threshold

## 11. Batch results

Authorized unique TRAIN + DEVELOPMENT_EVAL assets: 14.

All 14 were exported successfully as edited HQ. No Paris 2819 / `IMG_1937`, final holdout, protected F0 holdout, unrelated corpus media, or obsolete experiments were included.

## 12. Failure breakdown

- `RECOVERED_ALIGNED`: 11
- `RECOVERED_DETERMINISTIC_MAPPING`: 1
- `TEMPORAL_MISMATCH_QUARANTINED`: 2
- `ICLOUD_DOWNLOAD_FAILED`: 0
- `PHOTOS_ASSET_UNRESOLVED`: 0
- `EDITED_HQ_EXPORT_FAILED`: 0
- `STORAGE_BLOCKED`: 0

## 13. Durable storage

Media remains outside Git under `/Users/Shared/services/data/media-node/highres_analysis_source_v1/`.

Tracked manifest: `docs/science/HIGHRES_ANALYSIS_SOURCE_MANIFEST_V1.json`.

Local M2 audit copies are under untracked `runs/highres_recovery_v1/`.

## 14. Quality audit

M2 audit file: `docs/science/HIGHRES_QUALITY_AUDIT_D5_CANARY_V1.json`.

Subset:

- `133`: clean control
- `2169`: HURDLE
- `676`: difficult water-entry/small-diver example
- `311`: known D5/EL failure, overlapping PTS only because temporal mismatch prevents event-label transfer

Findings:

- HQ materially increases diver pixel height in all sampled dives.
- HQ increases raw candidate counts for every sampled dive.
- D5 confidence and IoU are mixed: `2169` improves IoU, `133` slightly worsens IoU, `676` needs a crop-aware mapping before IoU is meaningful, and `311` is temporally quarantined.
- No retraining was performed.

## 15. Optional 720p

`720P_ANALYSIS_PROXY_CANARY` was not generated in this run. Native HQ shows useful signal but mixed D5 behavior and two temporal quarantines; a 720p derivative should be evaluated only after a crop/timebase-normalized representation contract is specified.

## 16. Resolution decision

`HIGHRES_BENEFIT_PROVEN_BUT_PRODUCTION_REPRESENTATION_UNDECIDED`

High resolution is valuable as recovered source material, but the production analysis representation should not be finalized as native HQ until crop/orientation/timebase normalization is specified and compared against a controlled 720p derivative.

## 17. Production implications

- `ANALYSIS_SOURCE_HQ_V1` is frozen as a durable edited-HQ source contract with per-asset temporal authority.
- Existing temporal labels may transfer only for 12 assets: 11 direct PTS-equivalent plus 1 deterministic mapping, excluding `311` and `524`.
- `311` and `524` require separate temporal diagnosis before any label reuse.
- Future layer-2 work should preserve HQ source media for pose, human masks, silhouette, joint angles, body configuration, and personal comparison.
- Detector status remains `NO_RETRAIN_AUTHORIZED`.
