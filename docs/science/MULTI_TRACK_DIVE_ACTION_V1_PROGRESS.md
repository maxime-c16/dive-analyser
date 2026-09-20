# Multi-track dive-action V1 progress

## 2026-09-20 — fresh preflight

- Packet: DIVE_ANALYZER_MULTI_TRACK_DIVE_ACTION_V1.
- Canonical: diveanalyzer-server:/home/mcauchy/dive-analyser, branch uiux-overhaul-pro-app.
- Starting HEAD: 1d49bbead2c230b44ab42c76958c24eac5fe1a35 (matches accepted L0).
- Dedicated local worktree: /Users/maximecauchy/.perso/diveanalyzer-multi-track-v1.
- Branch: dive-analyzer-multi-track-dive-action-v1.
- Original cwd is a non-Git reference slice, not canonical.
- Canonical pre-existing tracked deletions: subject-resolution audit MD/JSON, DB export JSON, audit script and test. Preserve all. Existing untracked detector/annotation work and four server worktrees also preserved.
- No experiment run yet. No inference, training, media access, protected data access, or authority mutation.
- Next: reconstruct frozen D5/V3/Event Logic/GT/cache authorities, freeze an identity-free formulation, run cache-only evaluation, validate, document, commit, integrate canonical, sync mirror.
- L0 remains IDENTITY_MATCHER_L0_FAILS; identity research and reference acquisition deferred.
- This log is a recovery checkpoint, not a completed-results claim.

## Cache experiment completed; validation/reporting in progress

- Protocol frozen before inference: 95d1de59261526d423fadd3f979607fd7e3d7156.
- Commands: `python3 experiments/subject_resolution/run_multi_track_action_v1.py preflight`, then `caffeinate -i -s python3 experiments/subject_resolution/run_multi_track_action_v1.py infer`, then `... evaluate`.
- All 15 clips completed sequentially in 82.37 s; peak process RSS 666,681,344 bytes on this Mac. No media decoding or new model work.
- Host-only per-track outputs: `runs/multi_track_action_v1/` (~278 MB, explicitly gitignored). Every raw/merged trajectory, provenance, events, ranks, labels, representative frame, quality, PTS, authority/resource manifests retained.
- 34,320 raw tracks + 6,490 merged alternatives; D0 117 positives, D1 62 positives. D0/D1 anchor-correspondence recall both 1/15 (2387, rank 3). Strong >=75% subject-anchor coverage recall 0/15. Sole retained subject candidate covers 23% of anchors; event errors 2.648/2.164/0.929 s. Not downstream-ready.
- Bounded merging does not improve best qualifying subject coverage on any clip. Next blocker is association, not mandatory identity resolution.
- Evaluator initially assumed every event was HUMAN-valued; fixed handling of 311 apex NOT_APPLICABLE (kept unscored). No authority changed.
- Initial test fixture used 10 fps, incompatible with frozen R5 0.08 s gap. Corrected fixture to 30 fps; 12 tests then passed. Adding actual simultaneous synthetic dive replay check next.
- Remaining: final report/contract, final tests, commit, canonical merge preserving dirty work, mirror sync, exact HEAD verification.

## Final science validation complete — integration next

- Final regeneration completed after explicit D0-negative quality-separation correction; D0 positives and all D1 decisions unchanged. Final inference 83.90 s, RSS 611,598,336 bytes. Two cache-only passes total; no model/media work.
- `python3 -m pytest -q experiments/subject_resolution/test_multi_track_action_v1.py`: 14 passed in 4.20 s, zero failures. Includes real synthetic simultaneous positive Event Logic replay and real 1040 full-inference determinism.
- Report MD/JSON, analysis-track contract, protocol amendment and union-style PROJECT_STATE complete. Event GT proxy SHA checked on all nine authority clips. `git diff --check` clean.
- Final classification NOT_READY; next IMPROVE_TRACK_ASSOCIATION_NEXT; synchro representable, whole-action overlays insufficient. False/action legitimacy counts correctly unknown.
- Canonical rechecked before integration: still 1d49bbead2c230b44ab42c76958c24eac5fe1a35, same pre-existing dirty entries.
- Next commands: commit only packet files; push science branch to canonical server; fresh canonical HEAD/status check; no-ff merge; push canonical to mac-mirror; verify remote mirror SHA; save exact commit/HEAD integration receipt outside Git and report to user.
