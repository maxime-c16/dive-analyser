# Experimental AnalysisTrack contract V1

Artifact-level science contract; no production database migration or UI implementation.

## Distinctions

A PersonTrack is a temporally associated person hypothesis, regardless of action. A DiveTrack is an eligible action-bearing PersonTrack or bounded chain of fragments. Several DiveTracks may overlap. Neither identifies the product subject. Raw proposals are not certified physical people; several hypotheses can describe one person.

`Dive.diver_id` remains product/default-subject authority. `analysis_subject_track` is an independent selection. No `PRIMARY_DIVER` is emitted.

## Artifact schema

Clip envelope: `clip_id`, frozen input/proxy SHA, authority/version IDs, recorded frame PTS, raw PersonTrack count, association edges, `tracks[]`, product state, ambiguity state.

Each track exposes:

- `track_id`: deterministic raw/fragment-reference hash; scoped to clip + input cache SHA + protocol/version. Not a cross-clip person ID. Stable for identical ordered proposals and algorithm version.
- `person_track_refs`: frozen R5 raw IDs, retained even when association adds a hypothesis.
- `temporal_extent`: inclusive first/last observation PTS seconds in the individual clip's existing proxy timebase.
- `association_provenance`: raw R5 or mutual-best PTS fragment chain; envelope edges contain gap and prediction residual.
- `status`: DIVE_LIKE, NON_DIVE, or AMBIGUOUS; D0/D1 inspectable. Not a calibrated probability.
- `trajectory[]`: zero-based source frame index, actual PTS, normalized center-format box, detector confidence. Missing frames absent, never silently extrapolated; Event Logic uses its frozen internal interpolation.
- `quality`: frozen V3 support statistics and confidence/size measures; temporal coverage and longest observation gap supplied separately.
- `procedural_events`: nullable takeoff/apex/water-contact PTS; `procedural_sequence`: NO_VALID_DIVE_SEQUENCE, PARTIAL_DIVE_SEQUENCE, COMPLETE_DIVE_SEQUENCE. UNKNOWN context applied uniformly. Success establishes neither physical validity nor identity.
- `representative_frame`: highest-confidence observed frame, earliest-frame tie break; index and PTS support seeking the existing frozen proxy. No new media tier.
- `events_available`: at least one landmark; `analysis_available`: false until downstream analysis is implemented/validated. Complete sequence alone does not set analysis availability.
- `rank`: generic support/action ordering, never identity confidence. No rank-based deletion. UI must distinguish duplicate hypotheses before presenting physical-dive counts.

## Selection and overlapping actions

Future `default_analysis_track` may use known diver matching, automatic ranking, or previous user choice. Users must be able to override it. Persist choices per user + clip/media revision + track/protocol version; do not modify another user's choice or `Dive.diver_id`. Reconcile selection when inputs or track identity change.

Simultaneous tracks have independent trajectories, event dictionaries, and selections. No exclusive global active-track slot. A synthetic two-diver replay through frozen Event Logic tests this. This is representability, not synchro validation.

## Product state

Positive hypothesis count yields NO_DIVE_TRACK_FOUND, ONE_DIVE_TRACK_FOUND, or MULTIPLE_DIVE_TRACKS_FOUND. AMBIGUOUS_TRACKS is an additional nonexclusive flag. These count hypotheses until duplicates/false positives are resolved. Allow candidate inspection even without positives; NON_DIVE can describe a stationary preparation fragment of someone who later dives.

## Overlay and future attachments

Observed boxes can be rendered for inspection. Masks, silhouettes, and pose can later attach by `(clip revision, track version, frame_index, pts_s)` with validity/occlusion flags. No segmentation introduced. Whole-action continuity is not validated: `TRACK_STABILITY_INSUFFICIENT_FOR_OVERLAY`. Diagnostic box drawing remains possible. Manual selection is a viable interface contract, but selecting a short or contaminated track cannot recover missing action coverage; reliable end-to-end fallback remains unproven.

## V2 path-decoding addendum (experimental, no migration)

Association V2 retains bounded top-K decoded paths (`TOP_K = 5`) rather
than merged hypotheses. Each retained path additionally exposes:

- `path_id`: equals `track_id` (deterministic hash of ordered fragment refs).
- `person_track_refs`: ORDERED carrier fragment IDs (decoding order).
- `handoff_provenance`: ordered list of `{kind, from, to, key}` with kind in
  `{gap, overlap, interleave}`; `key` is gap seconds, handoff frame, or
  `[h, j]` handoff interval. Carriers contribute only their inter-handoff
  segment; missing frames stay absent.
- `path_rank` / `path_score` / `continuity_score`: identity-free ordering
  among retained alternatives, never identity confidence.
- `mean_handoff_appearance`: nullable frozen-OSNet local compatibility
  (A1 clips only); null means no cached embeddings, never a penalty.
- `association_provenance`: `A0_CONTINUITY_PATH` or
  `A1_CONTINUITY_APPEARANCE_PATH`.

`DIVE_LIKE` on an unattributed retained arc remains a downstream
diagnostic, not a correctness label. No production DB migration.
