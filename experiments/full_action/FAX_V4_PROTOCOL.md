# FAX4 raw-only reattachment gate

2026-09-27. The candidate queue was fixed from prior metadata shortlists and
raw B2 frames before opening any S3/FSR outcome for these four clips. All
sources were fetched read-only and SHA-checked against the metadata records.
The sessions are distinct from each other and from FAX3B's s26/s27/s34/s33.
All four remain in the denominator, including clips later found unlabelable
or without a qualifying selected flight. There is no outcome-based reserve.

| Dive | Session | Code | Source SHA256 | Raw screen |
|---|---:|---|---|---|
| 2473 | 140 | 301C | `c8b938ef944e63ce376c96a353a9c2aecdeec644835897d91dcad889c532a0b8` | Two people near springboards |
| 2533 | 148 | 5122D | `479ea1efce967155c77cbd7fd35851d5e6fc1c9879d66bdd4eade0265b9235e6` | Airborne diver and nearby swimmer |
| 410 | 35 | 101C | `5fcffbfcfeaf5fc56393d16e1940d47b99fee3d6b8543df339ef8469668c22e1` | Board figure and foreground swimmer |
| 1667 | 102 | 103C | `b5fd09d94c4b1b9d42444748497fb423941ebd037bbd2723664a2aaf76c3aa7d` | Board figure and foreground swimmer; visibility may be limited |

The raw screen used source snapshots at 6 and 12 seconds only; it did not
inspect model boxes or tracking scores. These are close-person opportunities,
not a claim that any selected detector path actually merges. The annotation
UI shows verified study-local proxy frames only, with no S3/FSR/FAX data.
HUMAN marks takeoff, contact, independent apex repeat, flight ninths,
0.5-second preparation boxes, immediate post-entry boxes, and one blind prep
repeat per dive. Annotator exclusions remain in the denominator.

The sealed queue manifest is `docs/science/FAX4_QUEUE_MANIFEST.json` (SHA256
`9045e045aeb38b923a041933363fcf0d8f46611d60c360bbde4a7863cfb65a1d`).
The host-only proxy registry SHA256 is
`617f7c26c29daf4f898d3f258c66ccdd41316b75ed1108dc5a147009d2fe100f`.

The queue and source identities must be committed before running S3 or
inspecting selected paths. Freeze the HUMAN manifest before opening detector
results. Keep FAX3B consumed for development. Evaluate correct continuation,
correct reattachment, honest abstention, wrong-person continuation, first
wrong-link time, unresolved duration, prep/flight/post coverage, and overlay
stability. Visual adjudication distinguishes a box-center miss from an
identity switch. No `diver_id` enters inference.
