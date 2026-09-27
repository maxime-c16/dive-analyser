# FAX3B targeted mixed-person fresh authority

2026-09-27. This second queue was chosen after FAX3's four-dive fresh round
showed zero mixed selected-flight edges and identical V1/V2/V3 output. FAX3
was consumed before FAX3B selection. The V3 code and thresholds remain frozen
from `5a29f85`; no tuning is permitted on FAX3B labels.

Selection used only DB metadata and raw B2 contact sheets. Source SHA256s
were verified against `media_blobs`; no S3 boxes, FSR paths, track scores or
HUMAN labels were used. Four session-disjoint clips: 164/s26 (two people on
adjacent boards), 200/s27 (multiple occupied boards), 389/s34 (two people
beside the springboard), 373/s33 (cleaner close-person control). All show
visible preparation. There is no reserve. Clips with no mixed S3 box remain
in the denominator. Prior science and protected sessions were excluded by
dive/session authority screening.

The raw-only annotation UI uses the same event, nine flight, 0.5-second prep,
post-entry and blind-repeat rules as FAX3. Annotator exclusions remain in the
denominator. The file-hashed `FULL_ACTION_GT_HUMAN_FAX3B_FRESH` manifest must
be frozen before inspecting the detector cache. The selected flight is the
first Q-ordered candidate meeting the established 2-hit, 0.75 coverage and
0.75 purity rule at normalized radius 0.06. HUMAN only emulates the user's
correct selection.

Score correct continuation, honest abstention and wrong-person continuation
separately. Review group boxes and candidate alternatives visually. A
center-radius miss is not automatically a person switch; visual adjudication
must distinguish localization error. Report mixed incidence, first wrong
link, longest missing interval, flight preservation and box stability.
