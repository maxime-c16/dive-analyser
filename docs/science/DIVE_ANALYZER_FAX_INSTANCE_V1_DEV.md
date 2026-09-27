# FAX instance bridge V1: development signal, not promotion

The frozen S3/FSR selected core is provenance. Prototype source SHA256:
`46db2213e4e21f206d58746a57ea26adeaeea353bb0e68a4e5369cbf4731944f`.
A mixed initial box is not
used as an identity anchor. A separate, SHA-pinned local person-segmentation
model (`yolov8n-seg.pt`, SHA256
`a7cd8f929e1903d78a12a48efecab430209f18dc46cb96c3599a5980c63c423c`)
produces individual masks from read-only high-resolution frames. Three
consecutive source-supported, person-specific masks later in the core form
a candidate trusted subcore. Bounded bidirectional geometric links form
local paths, with competing/unsupported links left NULL. The output carries
compressed individual masks and an explicit unresolved interval. No
cross-clip appearance model, HUMAN geometry, or `diver_id` is used in inference.

Consumed development only: 164 (FAX3B), 205 (FAX2), and 590 (FAX5) each
produced a later asserted target-mask run after a mixed edge. First assertion
occurred 0.283, 0.217, and 0.133 seconds after the edge respectively.
Sampled flight-center hits among asserted anchors were 4/5 on 164, 6/6 on
205, and 5/5 on 590. The 164 center miss at frame 269 still visibly masks
the selected airborne diver, illustrating why center hits are not identity
adjudication. These clips were used to design and adjust the prototype,
so these are feasibility observations only, not a safety rate.

The path selector currently ranks by supported run length and score. A
wrong continuous branch could outrank the target; the near-length conflict
gate is not a proof against that. General full-action overlays remain unsafe.
FAX6 is a raw-only, session-disjoint blind HUMAN gate for this candidate.
