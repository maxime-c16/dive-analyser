# FAT3 fresh full-action annotation queue V1 (COMMITTED BEFORE ANNOTATION)

Task for Maxime. Goal: fresh session-disjoint DEVELOPMENT authority for the
frozen FAX V1 gate in the visible-preparation regime, combined with
Event Logic successor validation (takeoff / water contact / apex events).
Everything below is fixed before the first label.

## Dives (6 sessions, all unused in every training/consumed/DEV role)

| Dive | Session | Code | Height | Family | Source dur | Proxy frames | Proxy size |
|---|---|---|---|---|---|---|---|
| 16 | 7 | 101C | 1m | standing | 20.25 s | 665 | 648x360 |
| 251 | 31 | 201C | 1m | hurdle | 14.74 s | 884 | 202x360 |
| 1491 | 92 | 401B | 1m | standing | 14.68 s | 880 | 202x360 |
| 1716 | 104 | 201C | 1m | hurdle | 10.99 s | 329 | 202x360 |
| 2519 | 139 | 201C | 1m | hurdle | 16.13 s | 968 | 202x360 |
| 2742 | 166 | 5122D | 1m | hurdle | 12.03 s | 722 | 202x360 |

Reserve (enters ONLY if a queued dive is annotator-excluded, identical steps):

| Dive | Session | Code | Height | Family | Source dur | Proxy frames | Proxy size |
|---|---|---|---|---|---|---|---|
| 735 | 47 | 301C | 1m | standing | 15.19 s | 456 | 200x360 |

No dive has prior boxes/events in any authority. No detector output, search
result, or candidate track exists for any of these dives at queue-commit
time (S3 caches are built GT-free after this commit and stay sealed).

## Selection rule (pre-registered, GT-free)

1. DB metadata filter (canonical DB, read-only): sessions disjoint from all
   51 forbidden sessions (past-science 37 + FGT3H/V3-holdout 13 + FAT2 80,
   incl. INTERNAL_EVAL sessions and the sessions of 524/2555/Paris);
   non-lineup, non-sync, springboard 1m/3m, `photos_edited_rendition`
   source >= 10 s. Result: 904 dives / 82 sessions.
2. Metadata shortlist (no pixels seen): 10 sessions spread 2024-11..2026-08
   (7/19/31/47/69/92/104/124/139/166); one dive per session preferring 1m +
   longest clip, alternating standing/hurdle families.
3. Dive-context sweep: none of the 10 shortlisted IDs appears as a dive
   reference (`dive_id` fields across all 111 referenced science JSONs;
   dive-context regex over all 1886 tracked docs/experiments files). All
   remaining hits are plain-number collisions (confidences, coordinates,
   percentages, counts, frame indices).
4. Raw-clip screen (study-local 360p proxies, contact sheets, NO detector
   output): rank by longest observable near-figure preparation.
   - Rank: 16 > 2519 > 2742 > 1716 > 251 > 1491 > 735 > 1083 > 77 > 1933.
   - Cut at 6 for annotation burden (~200 steps). Reserve = rank 7 (735).
   - Rejections: 77 (portrait, small distant figure at frame edge);
     1933 (tiny distant figure in dark wide shot, 2838-class unlabelable
     risk); 1083 (foreground close-up person at clip start, short board
     prep ~2 s); 735 held as reserve (small figure, weaker of the
     small-figure pair vs 1491).

## Steps per dive (~35; ~200 total + 6 apex repeats + 6 box repeats)

1. Mark takeoff (scrub the clip; first frame of true departure).
2. Mark water contact (first frame of true entry).
3. Mark apex (highest physical point; must lie inside [takeoff, contact] —
   the tool enforces this; mark takeoff/contact first).
4. Mark apex again independently (apex_R; frame-choice agreement measure).
5. Draw the diver's box on each presented frame (flight k/8, prep every
   0.5 s from clip start, post +0.1/+0.3/+0.5 s, one blind PREP repeat):
   visible / partial with a tight box, else not_visible / ambiguous.
   Annotate the diver who performs the dive, even if others appear.

## Blindness and seal (read carefully)

- The UI shows ONLY raw study-local proxy frames.
- You will NOT see any detector boxes, candidate tracks, scores, or overlays.
- Until the freeze is recorded: DO NOT open `runs/full_action_fat3/sealed/`
  (it contains GT-free S3 caches + FSR selection output for the 6 queued
  dives + reserve) and avoid `runs/full_action_fat3/overlays/`.
- The S3 selection for these dives is computed GT-free and sealed; your
  labels emulate the user's click after the freeze.

## Run

```bash
python3 experiments/full_action/fat3_annotation_v1.py serve --port 8766
# open http://127.0.0.1:8766, work top to bottom
python3 experiments/full_action/fat3_annotation_v1.py validate   # counts only
python3 experiments/full_action/fat3_annotation_v1.py freeze     # writes the authority
```

## Media identities (frozen at queue commit)

B2 edited sources (read-only fetch, SHA-verified = DB `media_blobs.sha256`):

| Dive | edited_blob_sha256 (prefix) | bytes |
|---|---|---|
| 16 | 7d50c7634eaf…2421dd | 30206691 |
| 251 | d1b0d8bb7653…460d6 | 22931984 |
| 1491 | 9ac249846810…5ef62f | 25477614 |
| 1716 | 22bb28b95ce9…27b5982 | 12912923 |
| 2519 | 2d9a9a229afa…03c4c64 | 26666499 |
| 2742 | a8fc77a54a2a…cd221a62b | 32193316 |
| 735 (res) | 60d5186838e47…15ab180f | 21784261 |

Study-local 360p proxies (frozen mac-agent recipe = fpsr2_prepare_media args;
`runs/fat3_media/` host-only):

| Dive | proxy_sha256 (prefix) | frames | size |
|---|---|---|---|
| 16 | 0bd5b9cfc001 | 665 | 648x360 |
| 251 | d2d1d784fb55 | 884 | 202x360 |
| 1491 | a9f1fbfb6ae1 | 880 | 202x360 |
| 1716 | ada7c0845050 | 329 | 202x360 |
| 2519 | 210bf6d389cd | 968 | 202x360 |
| 2742 | fa0d464752db | 722 | 202x360 |
| 735 (res) | e96a90d62617 | 456 | 200x360 |

Queue logic: `experiments/full_action/fat3_annotation_v1.py` (this commit).
Scrub/box frames are cached under `runs/fat3_annotation/` (host-only).
Gate rule: `docs/science/FAT3_PROTOCOL_V1.md` (this commit).
