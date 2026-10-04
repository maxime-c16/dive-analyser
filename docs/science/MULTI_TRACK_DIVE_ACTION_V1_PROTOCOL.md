# Multi-track dive-action V1 — preregistered formulation

Frozen before any packet inference/evaluation. Cohort is the accepted 15-clip L0 cohort, including its three fragmented cases. No L0 execution. No per-clip/family tuning.

PersonTrack is a temporally associated person hypothesis; DiveTrack is an action-bearing PersonTrack or bounded association of fragments. Neither implies product subject or identity.

Retain every frozen R5 raw tracklet, including unsupported short alternatives. Add disjoint, mutual-best successor chains using positive PTS gaps <= frozen Event Logic interpolation limit (0.30 s), frozen R5 size/velocity/displacement gates, and constant-velocity endpoint residual <= frozen V3 support radius (0.06). Break ties by stable raw ID. Do not delete originals. Chains are bounded by the finite clip and each edge by 0.30 s; temporally overlapping fragments cannot merge. Raw tracklet formation retains frozen nominal-fps semantics; all new timing, gap tests, events, and output coordinates use recorded PTS.

D0: replay frozen V3-C0 with empty dive code (UNKNOWN context, existing standing-like fallback) on each trajectory's full temporal extent, with missing observations explicit. No family dispatch. A DIVE_LIKE trajectory requires >=0.70 s extent (frozen V2 minimum), no observation gap >0.30 s, a strictly ordered complete event sequence, and observed downward displacement >=0.08 normalized cy after its predicted apex and before predicted contact (frozen V2 excursion margin). These are procedural eligibility hypotheses, not validated identity or calibrated probabilities. Sufficiently long, supported tracks with vertical range <0.08 and no complete sequence are NON_DIVE; remaining cases AMBIGUOUS. Camera motion and early Event Logic fallback events are known limitations.

D1: D0 plus frozen V3 Q0 support tier. Unsupported D0 positives become AMBIGUOUS. No other quality thresholds. Both formulations reported; D1 is designated primary in advance. Preserve raw and merged alternatives; counts are hypotheses, not deduplicated physical persons/dives. Nonexclusive product ambiguity flag coexists with the positive-count state.

Evaluation only: compare every raw/merged hypothesis with all existing visible HUMAN anchors (no oracle-reference split needed). Subject correspondence requires >=2 matching anchors and >=0.75 purity among overlapping anchors (accepted L0 MATCH semantics); also report matched/all-anchor coverage to expose fragment-only matches. Primary recall is any qualifying DIVE_LIKE subject hypothesis / all 15 evaluable clips. Stronger coverage >=0.75 is supplementary, not a changed primary. Unannotated other people are UNKNOWN, never automatically false. Report unmatched hypothesis upper bounds and no false-positive precision claim without action authority.

Human event errors use DEVELOPMENT_DESIGN YAML human timestamp_seconds with frame_pts_seconds alongside it; predicted events use actual cache PTS. Event scoring is post-inference, on best matching retained subject hypothesis selected by evaluation coverage then purity (explicit evaluation oracle, not default UI selection). No event-window lookup during inference.

No training, embeddings, new labels, media decode, B2 access, identity ranking, segmentation, UI or database migration. Protected clips 524/2555 and protected collections excluded. ARMSTAND and reference acquisition deferred.

## Compliance correction after first run (not a threshold or positive-rule change)

Code review found that the NON_DIVE clause above used V3 support within D0, conflicting with the packet's evidence-only D0 separation. Corrected D0 to classify coherent static fragments without quality; D1 applies frozen Q0 support to both resolved labels, demoting unsupported labels to AMBIGUOUS. D0/D1 positive decisions and D1 negative decisions are unchanged. No numerical constant, association edge, or event parameter changes. Regenerate outputs and test this separation explicitly. Original preregistration remains available at the protocol commit.
