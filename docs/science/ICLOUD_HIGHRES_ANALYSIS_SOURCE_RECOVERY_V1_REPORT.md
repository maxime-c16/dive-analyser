# ICLOUD_HIGHRES_ANALYSIS_SOURCE_RECOVERY_V1_REPORT

**Date:** 2026-09-09  
**Canonical repo:** `mcauchy@192.168.1.57:/home/mcauchy/dive-analyser`  
**Branch:** `uiux-overhaul-pro-app`  
**Starting HEAD:** `cb565ea47d48254761d2ec41e07fca1de1ec7a5e`  
**Status:** `BLOCKED_TCC_PHOTOS_AUTHORIZATION`  

## 1. Photos/iCloud status

`PHOTOS_LIBRARY_HOST` is `mac-server.home` / `192.168.1.19`, user `divesensei`,
macOS 15.1.1, x86_64. Photos library:
`/Users/divesensei/Pictures/Photos Library.photoslibrary`.

The deployed media agent is `com.diveanalyzer.agent`, PID observed as running via
the app wrapper `DiveSensei Python Runtime.app`. Deployed venv:
`/Users/Shared/services/data/diveanalyzer/venv`; `osxphotos` version 0.76.1;
ffprobe version 8.1.2-tessus.

With `LC_ALL=C LANG=C`, osxphotos can open the Photos database and reports 12,276
movie assets. Without that locale repair, SSH-launched osxphotos fails with
`locale.Error: unsupported locale setting`.

## 2. Previous failure history

Prior high-resolution recall established the scientific invariant: raw Photos
masters are not automatically equivalent to the analysis timeline because users
trim/edit videos in Photos before ingestion. Prior reports also identified
`--skip-edited` as scientifically invalid for direct PTS transfer unless a
temporal transform is proven.

## 3. Canary recovery

Planned canary set:

| Dive | Role | Reason | mac-media-01 UUID | Photos status |
|---|---|---|---|---|
| 133 | DEV_EVAL/TRAIN | clean control, small file | `ABD32644-4536-416F-9572-86849FCF15B5` | cloud-only |
| 311 | DEV_EVAL/TRAIN | known D5/EL failure analysis | `D0C33293-F4B7-4A57-9368-9C53BFC32033` | cloud-only |
| 676 | DEV_EVAL/TRAIN | 360p-noise failure | `AA890D9A-A8AE-44C4-B6A4-C82BDAD56F46` | cloud-only |
| 2169 | DEV_EVAL/TRAIN | perception-difficult D5 sample | `B6AC3A80-752B-439F-A927-01550A6F52C1` | cloud-only |

The AppleScript `--download-missing` path started for dive 133 but produced no
bytes after several minutes. The alternate PhotoKit path returned:

`Error: could not get authorization to access Photos library`

and requested "Allow Access to All Photos".

## 4. ORIGINAL_MASTER semantics

`ORIGINAL_MASTER` would be exported with `--skip-edited`. It remains evidence
only and is `SCIENTIFICALLY_INVALID_FOR_DIRECT_PTS_COMPARISON` unless the raw
master is proven PTS-equivalent or deterministically mappable to the Photos-edited
analysis source.

No original master was recovered in this run because the TCC canary failed.

## 5. Edited high-res semantics

The preferred candidate is `EDITED_HIGH_RES_RENDITION`, exported with
`--skip-original-if-edited` so Photos edits/trims are preserved where they exist.
This candidate was not recovered because PhotoKit export lacks TCC authorization
for the SSH-launched process.

## 6. Current proxy provenance

Fresh code inspection confirms the deployed materializer command uses
`osxphotos export TARGET --uuid UUID --only-movies --download-missing --update`
without `--skip-edited`. The normal current proxy path therefore derives from
Photos edited renditions when edits exist, not from raw camera masters.

## 7. PTS alignment

No canary video bytes were materialized, so no duration, PTS sequence, boundary,
or frame-fingerprint comparison could be performed. Canary temporal alignment is
`NOT_EVALUATED_TCC_BLOCKED`.

## 8. ANALYSIS_SOURCE_HQ_V1 freeze

`docs/science/ANALYSIS_SOURCE_HQ_V1_FREEZE.json` was created with status
`NOT_FROZEN_CANARY_GATE_CLOSED`. This is intentionally not an approval to use
high-resolution sources; it records the candidate contract and the blocked gate.

## 9. Batch scope

`docs/science/HIGHRES_RECOVERY_BATCH_V1.json` records the exact authorized scope:
14 unique assets from the active D5 train/validation lineage and the six
DEVELOPMENT_EVAL assets. Paris `IMG_1937` / dive 2819, FINAL_HOLDOUT, protected
F0 holdout, and unrelated corpus media are excluded.

## 10. Recovery results

Requested: 0 batch assets. Recovered: 0. Failed: 0. Batch was not started because
the required 3 successful canaries were not obtained.

## 11. Failure cases

Primary blocker: `BLOCKED_TCC_PHOTOS_AUTHORIZATION`.

Secondary operational finding: Photos host storage was initially below the
documented stop threshold. A policy-compliant cleanup removed 160 expired,
temporary, unpinned, inactive source-vault entries totaling 5,001,158,602 bytes.
Free space increased to 19 GiB.

## 12. Storage/provenance

Durable media destination remains outside Git under the existing media-node
authority. No high-resolution source files were retained. Canary scratch dirs were
removed after the failed export attempts.

## 13. Quality comparison

Not run. No high-resolution edited source was available. Prior Paris evidence
still suggests high resolution can improve detector signal, but this run produced
no recovered source from the authorized TRAIN/DEV_EVAL corpus.

## 14. Optional 720p result

Not run. 720p proxy generation is not justified until at least one edited
high-resolution source passes temporal alignment.

## 15. Scientific implications

Current answer to the success questions:

- iCloud propagation to the Photos Mac: catalog metadata is present; full-byte
  propagation/download is not proven.
- Full-quality download reliability: not proven.
- Edited high-resolution export: not proven; blocked by Photos TCC authorization.
- PTS equivalence to current proxy: not evaluated.
- Authorized batch recovery: not safe to start.
- High-resolution CV benefit: not evaluated on authorized corpus in this run.
- Production retention decision: defer. The design should retain a dedicated
  high-resolution analysis source only after edited rendition recovery and PTS
  alignment pass.

Resume action required on `mac-server.home`: grant Photos "Full Access" to the
process used for recovery, preferably the deployed `DiveSensei Python Runtime.app`
or the terminal/SSH-launched Python/osxphotos binary that will run the command.
Then rerun the 3-6 asset canary before any batch materialization.

Supervisor gate: `SUPERVISOR_REVIEW_AFTER_ICLOUD_HIGHRES_RECOVERY_V1`
