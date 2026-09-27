# Event Logic V4-B0 freeze note (frozen 2026-09-27, BEFORE FAT3 annotation)

**Decision: `V4_B0_FROZEN_FOR_FAT3_VALIDATION`.** The flight-anchored
takeoff successor is frozen on DEV design evidence only. FAT3 (fresh) and
Paris are untouched. Frozen V3-C0 is the unchanged baseline.

## Why a successor

On the 17 trustworthy FAX V1 DEV tracks, frozen V3-C0 takeoff errors are
systematic (−2.0 to −3.1 s on 7 tracks; median |err| 2.101 s, n=12):
takeoff = FIRST sustained rise after the FIRST stillness fires on the
earliest prep motion. The V4-A0 DEV probe (flight-anchored rise detection,
frozen thresholds) reduced this to −0.17…−0.48 s on 14/17 with honest
abstention on 3/17 — same trajectories, so the failure was event
semantics. V4-B0 freezes that direction plus the open calibration.

## What V4-B0 changes vs V4-A0 (one thing)

`TAKEOFF_BIAS_S = +0.23 s`: the DEV median rise-onset→last-contact offset
(n=14, median −0.226 s, no hurdle/standing structure). Rise onset includes
the final extension/push; HUMAN takeoff is first true departure. Plus an
anchor-consistency clamp (takeoff ≤ ft0; 3 DEV activations). Apex/wc reuse
V3-C0 bounded detectors unchanged — per-dive picks byte-identical to V4-A0
on all 17 DEV tracks, so apex/wc carry zero new-model risk into FAT3.

## DEV result at freeze (design evidence, not validation)

Takeoff median |err| 2.101 s (V3-C0) → 0.050 s (V4-B0), max 0.250 s;
wc median |err| 0.684 s → 0.267 s (same detector, better anchor).
SEARCH_BACK_S = 4.0 s is DEV-invariant over {3, 4, 5} s.

## What FAT3 will decide

On independently gate-passing full-action tracks: signed/absolute errors
for takeoff/apex/water-contact, V3-C0 vs V4-B0, abstention vs wrong
prediction separated. Bar (FAT3_PROTOCOL_V1): median |takeoff| ≤ 0.5 s
with apex/contact not regressed vs V3-C0. No tuning on FAT3.

Identities: module SHA `21ad37bb…`; tests SHA `fe40ca39…` (10/10).
