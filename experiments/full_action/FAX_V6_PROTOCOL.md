# FAX6 blind instance-reattachment gate

2026-09-27. The FAX5 labels/results and FAX3B development evidence were
consumed before this queue. The instance-mask prototype was developed on
164 (FAX3B), 205 (FAX2), and 590/s42 (FAX5), so none is validation.
This queue is four further session-disjoint DEVELOPMENT dives, selected
from eight metadata candidates by raw source snapshots at 2/4/6/8 seconds.
No S3/FSR/FAX output or HUMAN geometry from these clips was inspected.
The nonselected raw-screened clips were 703/s46 (single diver), 711/s47
(distant board scene), 795/s50 (less overlap), and 823/s51 (single diver).
All source objects were fetched read-only from B2 and SHA-checked.

| Dive | Session | Code | Source SHA256 | Raw screen |
|---|---:|---|---|---|
| 649 | 45 | 201B | `d773598d9fade0af2ce5f72506525d7eb0de1c079ae24accdfb5340a8bc3b77a` | Airborne target with nearby board and pool figures |
| 745 | 48 | 201C | `54e0ac743f4c32e687e16a2c87ec70d823335fcb1abe7438a949a5c49ccdd577` | Multiple divers on stacked boards |
| 772 | 49 | 201C | `0ec6a49eeb8d656d1d357c2ff2ff8ae48033af3c274f3a2c9063ae16f41b0730` | Board diver with another person nearby |
| 850 | 52 | 201C | `823e716613848b1e057725aad7aa51a2373ce252580dd45ede59c548e23b1c62` | Multiple people in board view |

Queue manifest: `docs/science/FAX6_QUEUE_MANIFEST.json`, SHA256
`5813d48740f91039f04ef6ebd438361f8df3431e616eeefd4fe8e888ebeab3d5`.
Host-only verified proxy registry SHA256
`095816a83c519dccabac1f3d1cf054f379f90448b07f1dce4a032c70b0c96983`.
All four remain in the funnel denominator, including exclusions and cases
without a selected flight. The annotation UI shows raw study-local proxies
only, with the established event, flight-eighth, prep/post, and repeat rules.

Seal blind HUMAN labels before any detector inspection of FAX6. Then run
the frozen prototype and V1/V2/V3/V4 controls; adjudicate physical identity
from raw frames separately from box-center misses. Score correct continuation,
reattachment, NULL, wrong-person continuation, first wrong link, unresolved
duration, prep/flight/post coverage, and overlay stability. No `diver_id`
enters inference; protected authorities and B2 stay untouched.
