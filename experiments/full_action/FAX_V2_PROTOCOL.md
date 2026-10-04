# FAX V2 development protocol — frozen before FAX2 labels are read

## Question and inference boundary

Given one user-selected flight candidate, extend its box trajectory through preparation and entry on the same physical diver. Do not use `diver_id`, HUMAN boxes, event labels, or identity metadata in inference. Keep all other flight candidates intact. Every unsafe continuation must be represented as absent boxes with a labeled stop.

V1, S3, FSR, V3-C0, and V4-B0 are read-only baselines. V2 may change only association after the flight selection. Its present development implementation is `fax_extension_v2_dev.py`; the FAT3-only safeguards are explicitly a candidate, not a validated freeze.

## Fresh authority, selected without model output

The DB metadata filter required edited-rendition B2 media, non-lineup, non-sync, 1m/3m, and duration at least 10 s. Prior science sessions from `FLIGHT_PERCEPTION_RECOVERY_SPLIT_V2.json` (37), FAT3 sessions (7/19/31/47/69/92/104/124/139/166), FAT2 session 80, FGT3H/holdout sessions (12/33/38/52/59/61/86/101/111/127/133/142/165), and protected INTERNAL_EVAL/Paris/524/2555 sessions are excluded. All shortlisted dive IDs had zero `dive_id` references in science JSON authorities. A raw contact-sheet screen, without detector or track output, ranked eight metadata-shortlisted clips by visible preparation and crowd interaction.

Main queue (one session each): 205/s28, 1751/s112, 1621/s100, 1363/s84. Raw-screen reasons: 205 has multiple people at the springboard and long visible preparation; 1751 has foreground crossing people; 1621 has multiple visible action periods; 1363 has long board preparation and a distant figure. Reserve 1440/s88 enters only if a main dive is HUMAN-unlabelable. Rejected after raw screen: 1998 (foreground person leaves before long empty scene), 2115 and 2231 (tiny distant figures, weak identity ambiguity). Source bytes were read-only B2 GetObject and checked against `media_blobs.sha256`; host-only `METADATA_SHORTLIST.json`, source clips, raw contact sheets, proxies, and `PROXY_REGISTRY_FAX_V2.json` record exact identities and PTS. The queue manifest records proxy SHA256s.

## Blind labels and evaluation

The HUMAN viewer at `fax_v2_annotation.py` shows raw proxy frames only. Per dive: takeoff, contact, apex and independent apex repeat; flight boxes at k/8 of that window; prep boxes every 0.5 s before takeoff; post-entry boxes at +0.1/+0.3/+0.5 s; one blind mid-prep repeat. Visibility is `visible`, `partial`, `not_visible`, or `ambiguous`. For a crossing occluder, box only the visible part of the selected diver and mark partial; if fully hidden, mark not visible; if identity cannot be determined, mark ambiguous. The annotator can exclude an unlabelable dive with reason; reserve activation is automatic. No model output is surfaced before authority freeze.

Score only visible and partial HUMAN anchors. For each selected flight, report correct hits (center distance <=0.06), wrong-person overlaps, missing anchors, abstentions/ambiguous intervals, flight coverage and purity, prep/full-action coverage, longest gap, and box stability (frame-to-frame center/area changes). Wrong-person continuation is the primary failure. Report conditional flight selection separately from association. A safe association gate requires zero wrong-person prep links, flight coverage >=0.75 and purity >=0.75 on every selected track, pooled prep coverage >=0.5, labeled stops, and no unstable overlay box jump left unflagged. Also report V1 alongside V2. Do not tune on FAX2 results and call them validation; any change after inspecting labels requires another session-disjoint authority.

Event Logic remains frozen until the trajectory gate passes. If it passes, investigate V4-B0 prep-rise lock on independently trustworthy tracks, comparing the dive-producing rise near the selected flight with earlier mount/bounce rises. Create a versioned successor only with a separately stated hypothesis and evidence.
