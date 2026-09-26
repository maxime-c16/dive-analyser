# FAT2 fresh full-action annotation queue V1 (COMMITTED BEFORE ANNOTATION)

Task for Maxime. Goal: fresh session-disjoint DEVELOPMENT authority for the
frozen FAX V1 gate. Everything below is fixed before the first label.

## Dives (3 sessions, all unused in every training/consumed/DEV role)

| Dive | Session | Code | Height | Reps | Status |
|---|---|---|---|---|---|
| 1190 | 75 | 201A | 1m | 360 + HQ (VERIFIED identity map) | no prior boxes/events |
| 1279 | 80 | 203C | 1m | 360 (decode-recorded PTS; no upstream index) | no prior boxes/events |
| 2838 | 202 | 103B | 1m | 360 (HQ exists but unaligned: 309 vs 557 frames) | no prior boxes/events |

Backup: 1194/s75 swaps in for 1190 only (same session; never added alongside).
Rejected pre-screen: dive 37 (reserve) shows an empty deck (no visible action).

Session-disjointness audit: S3-OOD train {16, 41}; S2/DS1/D-series design
{25, 32, 46, 48, 62, 66, 81, 94, 128, 134, 137, 144, 147, 148, 155, 156, 158,
160, 163, 164, 167, 203}; FGT3H consumed {12, 33, 38, 52, 59, 61, 86, 101,
111, 127, 133, 142, 165}; FAT1 DEV {9, 60, 98, 131, 140}; S3-OOD holdout
{141}. Fresh {75, 80, 202} intersect none of these.

## Steps per dive (~25; ~75 total)

1. Mark takeoff (scrub the clip; first frame of true departure).
2. Mark water contact (first frame of true entry).
3. Mark apex (highest physical point; must lie inside [takeoff, contact] —
   the tool enforces this; mark takeoff/contact first).
4. Mark apex again independently (apex_R; measure of frame-choice agreement).
5. Draw the diver's box on each presented frame (flight k/8, prep every
   0.5 s from clip start, post +0.1/+0.3/+0.5 s, one blind repeat):
   visible / partial with a tight box, else not_visible / ambiguous.
   Annotate the diver who performs the dive, even if others appear.

## Blindness and seal (read carefully)

- The UI shows ONLY raw proxy frames (1190 box frames are HQ resampled to
  proxy geometry under a verified identity map — same pixels, sharper).
- You will NOT see any detector boxes, candidate tracks, scores, or overlays.
- Until the freeze is recorded: DO NOT open `runs/full_action_fax_v1/sealed/`
  (it contains GT-free selection output) and avoid `runs/full_action_fax_v1/overlays/`.
- The S3 selection for these dives is already computed and sealed; your
  labels emulate the user's click after the freeze.

## Run

```bash
python3 experiments/full_action/fat2_annotation_v1.py serve --port 8765
# open http://127.0.0.1:8765, work top to bottom
python3 experiments/full_action/fat2_annotation_v1.py validate   # counts only
python3 experiments/full_action/fat2_annotation_v1.py freeze     # writes the authority
```

Media SHAs: 1190/2838 split-verified at serve time (FRESH_FLIGHT_HOLDOUT
role); 1279 `084d29b09aee095441a0c70c512ca9f5178d9a76942a570f5669eb449b102fbf`
(byte-recorded; no upstream index exists for this reserve dive). Queue logic:
`experiments/full_action/fat2_annotation_v1.py` (this commit). Scrub/box
frames are cached under `runs/fat2_annotation/` (host-only).
