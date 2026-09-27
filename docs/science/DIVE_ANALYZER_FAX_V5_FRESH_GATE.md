# FAX5 fresh mixed-person gate — V4 fails safely, without reattachment

2026-09-27. The raw-only four-dive queue was frozen at `a9fdb23` before
S3/FSR inspection. Blind HUMAN authority was sealed at `bccb41f`: three
labelable session-disjoint dives (590/s42, 321/s32, 474/s37), with 627/s44
HUMAN-excluded as an unlabelable replay-screen recording; all four remain
in the funnel denominator. The authority has 87 individual files plus
events and manifest, digest
`c178fd72fc68ff76f078783849c12178b0798accb6645ad704f30dedb23a230a`,
manifest SHA256 `1ee99d2144ec1ac96c3f94b23cc0b70ba9ad2925b02fdda552dbe7d878652bd4`.
Apex-repeat disagreement was 0.0334 s on each labelable clip. Source and
proxy hashes are in `FAX5_QUEUE_MANIFEST.json` and `FAX_V5_PROTOCOL.md`.
No protected authority, B2 object, frozen S3/FSR method, or `diver_id`
was used or changed.

Frozen S3 SHA256 `3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a`,
floor cache SHA256 `184b1fc9ba7d710dafb9beb1230ba7f6639b9f06048edd584d4933faba74c418`
with GT payload NONE. V4 bridge SHA256
`d13c53584e908d1d9a5ae40f7394d18cc5b1bdf5f2103c7538e7df102048e3b6`;
evaluator SHA256 `99ec4db53ee9d3780bfeeb22a5634cb45cb1a90d99cde468143d97dbe5edb10a`;
host-only results SHA256
`f5ae6ea4f1de55be22428b8608255f8af0a778ab373b8cc40474ee6763959394`.

Only 590 has a qualifying selected flight. 321's top candidate hits 2/7
visible HUMAN flight anchors (a lower candidate 4/7); 474's top candidate
hits 5/9. Both are upstream flight-surfacing failures and excluded from
selected-flight-conditioned association scoring, not from the funnel.

| 590 selected track | Correct prep | Prep NULL | Apparent wrong prep centers | Correct flight | Correct post | Mixed edge |
|---|---:|---:|---:|---:|---:|---|
| V1/V2 | 10/14 | 1 | 3 | 9/9 | 1/1 | unguarded |
| V3 | 0/14 | 14 | 0 | 0/9 | 0/1 | explicit NULL |
| V4 | 0/14 | 14 | 0 | 0/9 | 0/1 | explicit NULL; no reattachment |

Raw overlay review adjudicates V1/V2's three center misses at frames
30/60/90 as partial or downward-shifted boxes on the selected diver's
legs/board/water, not a physical-person switch. All other sampled prep
boxes follow the HUMAN target. First observed wrong-person link: none.
Thus V3/V4 do not reduce an observed silent switch on this authority;
they remove ten correct prep anchors and the entire useful flight overlay.
S3 has target candidates at all 14 visible prep anchors, so the lost prep
coverage is association/uncertainty design, not a prep perception bound.

590's selected source core has 50 boxes and all nine HUMAN flight-center
hits. Its first box at frame 423 (7.057 s) is broad, near another visible
person while the selected diver is airborne. V3 correctly represents a
possible group/NULL state, preserving the source path as provenance, but
never resolves it. V4 searches for a four-frame narrow suffix and lands on
frames 469–472 (7.824–7.875 s), after HUMAN water contact. Its 0.767 s
optical-flow bridge has only seven moving points entering that candidate
versus twelve on a competing box, so the safety gate abstains. It emits
zero asserted boxes. The first wrong-link time is therefore none; the
unresolved selected-source interval is at least 0.817 s from edge to core
end, and the visible full-action overlay is absent through post-entry.
Correct reattachment: 0/1 mixed selected-flight case; honest abstention:
1/1; wrong-person continuation: 0/1 observed. Those rates describe this
one selected opportunity and are not population estimates.

V1/V2 have three adjacent center steps above .06 on 590, maximum .086,
and a 0.1835 s internal gap; the source path still follows the selected
diver at sampled HUMAN anchors. V3/V4 have no asserted box stability to
score. General full-action box overlays remain unsafe. Event Logic and pose
stay frozen. The actual blocker is person-specific representation after
the mixed box: a width-only suffix rule skips a clear airborne target and
selects a late post-entry candidate. Higher-resolution instance masks are
the next bounded development direction; they must preserve explicit NULL
and be validated fresh before promotion.
