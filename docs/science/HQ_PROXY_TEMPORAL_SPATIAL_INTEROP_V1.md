# HQ / proxy / 720p interop note (V1)

How to translate timestamps and boxes between the three representations.
Authority: `docs/science/HIGHRES_ANALYSIS_SOURCE_MANIFEST_V1.json` (per-dive
`temporal_transform` / `spatial_transform`) and
`docs/science/HIGHRES_QUARANTINE_FORENSICS_V1.json`.

## Representations

| Arm | Meaning | Coordinate authority |
|---|---|---|
| `proxy_360p` | 202x360 (or matching) proxy, **label/GT timeline** | proxy-native pixels, normalized by annotation `width`/`height` |
| `canary_720p` | 720p transcode of the HQ display frame | HQ display coords, scaled by 720/1080 (portrait: w) or 720/1080 (landscape: h) |
| `native_hq` | edited Photos rendition, display-rotated | HQ display pixels (rotation applied) |

## Temporal translation

- **PTS_EQUIVALENT** (133, 524, 1040, 2169, 2341, 2353, 2387, 2541, 2555, 2625, 2661, 2680): `t_hq = t_proxy` (offset 0).
- **DETERMINISTICALLY_MAPPABLE, TRIM** (311): `t_hq = t_proxy - 12.125`. HQ covers proxy `[12.125, 19.2433]`; proxy timestamps outside that window have **no** HQ counterpart.
- **676**: PTS-equivalent (offset ~0).
- Always verify a candidate pairing with `ffprobe` PTS lists; do not assume CFR
  (HQ renditions are VFR; 1040's 720p canary drops 7 of 339 frames).

## Spatial translation (proxy-normalized -> HQ display)

Boxes annotated on the proxy (normalized x,y in [0,1]) map into HQ
display-normalized coords via the per-dive map `{x_off, x_span, y_off, y_span}`
as `hq = off + proxy * span`:

- identity (full-frame content): `{0, 1, 0, 1}` — 1040, 2169, 133, and all other aligned dives.
- **676**: `{"x_off": 0.0, "x_span": 1.0, "y_off": -0.00471, "y_span": 1.69468}`
  (HQ display 1080x1136 == proxy top band rows [0, ~213/360] upscaled x5.347).
- **524** (only if HQ-arm boxes are ever needed): hflip + 1.25 crop zoom; at
  480-wide portrait normalization, HQ point (u,v) -> proxy point
  `(u/1.25 + 93, v/1.25 + 8)`. No top-1 audit was run on 524; treat HQ-arm box
  math for 524 as unexercised.

Pitfalls learned the hard way:

1. The 676 map direction was initially inverted (HQ treated as the sub-window).
   The correct reading: **HQ is the cropped view**; the proxy frame always
   contains the full original FOV (except 311's temporal trim).
2. HQ `.mov` files are coded rotated (e.g. 1136x1080 with rotation -90). Decode
   with rotation applied (display dims) before any box or template math.
3. Template matching between HQ (sharp) and proxy (blurry) at patch scale fails
   spuriously. Blur-equalize both sides (e.g. 7-9px Gaussian) first; with that,
   NCC ~0.99 is achievable. Without it, expect false negatives.
4. "Black" regions seen in side-by-side sheets can be renderer padding, not
   video content — measure row means on the native frame before concluding a
   crop/letterbox.

## Provenance

- Mapping verification artifacts: `runs/hq_rep_v1/scale_match_*.json`,
  `runs/hq_rep_v1/offset_verify_311_stride1.json`,
  `runs/hq_rep_v1/sheets/676_gt_overlay_HQ.png`.
- Audit implementation: `experiments/landmark_pilot/hq_representation_audit_v1.py`
  (`DIVES[...]["map"]`), recomputation `hq_audit_recompute_v2.py`.
