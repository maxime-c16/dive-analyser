# FAX7 prep-to-subcore fresh blind queue

2026-09-28. Six DEVELOPMENT dives were selected from a 24-session metadata shortlist
using only raw source frames at 2/4/6/8 seconds. No detector, FSR, FAX,
instance-bridge, or HUMAN output was inspected. The shortlist SHA256 is
`ff6647be0a33154e1ae2ce8fd1eff55ef1f516f5002e7f813955e5e8d2c7659f`; the raw-screen selected manifest SHA256 is
`3c77d9f77e801df93f69de497f7fe0f6addad9acb08156229934c05ddd4779dd`.
All six sessions are distinct and excluded from the 76-session prior-science
and protected-session union. Source media were read-only B2 GetObject and
verified against production media_blobs.sha256; B2 was not mutated.

| Dive | Session | Source SHA256 | Raw screen reason |
|---|---:|---|---|
| 47 | 15 | `b4a6adc0266e5b3c6f2ddab256fa8d828b37936b1b4d30254eebfbbfb3e2f883` | two adjacent people on springboard during preparation |
| 884 | 53 | `39f0a08166ac6a7b8fd16dfe27c772abb3744507f825abf892a4b14952c2f9bf` | multiple people on stacked boards during preparation and dive |
| 952 | 58 | `aeecd01c891b607b6ff22f0c430ca20751825a627422ee5fd9a2733092c5042b` | board/deck people close to action lane |
| 1327 | 82 | `b4ba1563b6024ab3ca2b757691260f6ea18e01a6672499dcccedb4b61f11f522` | foreground pool person with board action |
| 1798 | 109 | `f8c6e51f32a1c3760c204b77ef30d46cd5e5f876c4a06134b496b5a28a5ebf52` | several people grouped by board during preparation |
| 2120 | 129 | `ad4baedef8189c33f0ebf5b9f282d56585e6fb3cbc59f1dbf858db5353491635` | several people beside springboard action lane |

Queue manifest: `docs/science/FAX7_QUEUE_MANIFEST.json` SHA256
`7eaecc0841a66ad993b3e6b301faead4382174dc6645942aeafefb58f070d0ae`.
Host-only verified proxy registry SHA256
`d173d89934b1c59a09eec058cb9085776927b6fda5dcc1df61d218707c4f86fd`.
Annotation UI source SHA256
`5102898b85cbcbd2297952a36e450594e019a1d30134e81f389a7fdc0cd5b12b`.
Frozen prep-to-subcore development method SHA256
`b71b3f3b4aa61d10fcef30809ecf87e750f30e0e3ac0c147b5a4a95d1319e404`.
No changes to S3, FSR, FAX history, instance-bridge V1, Event Logic, pose,
Media Backbone, or protected HUMAN authorities.

The blind FAX7 annotator shows raw study-local proxy frames only. HUMAN marks
takeoff, water contact, apex plus independent repeat, nine flight eighths,
preparation every 0.5 s, immediate post-entry, and one independent PREP
repeat per dive. Exclusions stay in the six-dive denominator. Seal all HUMAN
files and digest before loading S3/FSR or model-derived trajectories for
these six dives. The selected flight is supplied by the same FSR protocol
as FAX6; cases without a qualifying selected flight are upstream surfacing
failures and remain in the funnel.

Evaluate CORRECT_SAME_PERSON_CONNECTION, HONEST_UNRESOLVED, and
WRONG_PERSON_CONNECTION separately. Report prep/flight/full-action sampled
coverage, NULL duration, first wrong-link time, overlay stability, and
residual perception and surfacing attribution. No gate or pilot promotion
is allowed from raw-screen selection or consumed-data results alone.
