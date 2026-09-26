# Flight perception recovery V2: frozen evaluation protocol

Frozen split: `FLIGHT_PERCEPTION_RECOVERY_SPLIT_V2.json`, commit
`4d111da57514cce7dae5ec7e8751b96751b0076c` before any V2 fusion design.
The old `FLIGHT_GT_HUMAN_V2_HOLDOUT` is consumed and is now development diagnostic
evidence. The 14 new dives from 13 disjoint sessions in the split are sealed
`FLIGHT_GT_HUMAN_V3_HOLDOUT`. No detector or search output is used to select or
annotate them.

The human annotator marks takeoff and water contact from the raw edited-source
derived proxy, then draws boxes at k/8 of that window. Six repeat boxes audit
reliability. Unobservable dives are excluded by the human before model inference.
All boxes are direct HUMAN authority. Source B2 objects are read only and
SHA-verified to `media_blobs`; the science-local 360p proxy uses the frozen
mac-agent `proxy_360p` video recipe (audio omitted). HQ display frames are
used only when the proxy PTS and spatial map verify; otherwise the proxy is
shown. Image identity, proxy identity and dimensions accompany each box.

Model/fusion design may use the older V1 and V2 GT. D5 and
`S2_COCOinit_DS1` are immutable comparators. The FSR search, ranker, pool,
recovery radius and surfaced top-K remain byte-unchanged. The final V3 GT
is loaded once after the strategy, all parameters and code are committed.

Bounded development candidates are: F1, S2-first per-frame union with D5
boxes outside IoU 0.30; F2, select D5 for a clip representation only when
S2 has no detection at confidence 0.30 or above; S3, one 20-epoch fine tune
of a copied S2 checkpoint with the four consumed V2 failure dives added to
DS1. F1/F2 are assessed on consumed V2 diagnostics. S3 is admissible for the
fresh test only if its untouched FGT1 validation top-5 sum across 360/HQ is
at least S2's frozen 7 and its primary top-5 is at least S2's 3/6. If S3
passes, S3 alone is the primary V3 strategy; otherwise F2 is primary. D5 and
S2 are always evaluated as immutable comparators. No selection uses V3 results.

Per dive report raw presence at conf floor and 0.10; IoU and confidence rank/
margin; continuity runs; S0 raw, S2 graph, S3 pool, S3b extracted and surfaced
top-1/5/10. Report 360p and verified HQ separately, plus primary 360p+HQ,
stratified by resolution and OOD type. Multi-track viability requires top-5
at least 60% and top-10 at least 70% on sufficiently strong fresh HUMAN GT.
The denominator, uncertainty and all human exclusions are reported. This gate
is unchanged from `FLIGHT_PERCEPTION_SUCCESSOR_V1_PROTOCOL.md`.
