# FAX4 local motion bridge — consumed development readout

2026-09-27. This is a development probe on FAX3B, not a fresh gate or a
promoted full-action tracker. `fax_motion_bridge_v4_dev.py` reads the selected
flight source boxes, the S3 floor lattice, and a local proxy. It does not read
HUMAN geometry or `diver_id` during inference. The FAX3B HUMAN authority is
used only to emulate the user's selected flight and review the result.

Representation: a mixed selected-flight edge remains unresolved. A narrow
later source run is a candidate subcore. Sparse forward/backward checked
optical flow tests whether moving pixels from the mixed edge enter that run,
while stationary pixels and other boxes compete. A passing run gets only its
four narrow boxes asserted. Broad boxes after the run remain source evidence,
not person-specific overlays. This preserves NULL around the bridge.

On 164, V3 identified a mixed edge at frame 217 (3.617 s). The first
sustained narrow run is frames 241–244 (4.017–4.067 s). Of 171 initial
features, 146 survived the 0.4 s bridge; 23 moving features entered the
candidate, zero stationary features entered it, and the strongest competing
box received three moving features. Raw visual review confirms that the
candidate run encloses the airborne target. The bridge therefore produces a
*local* reattachment after 0.4 s of explicit uncertainty. It asserts only
four frames (0.05 s). The separate narrow run at 286–291 is not used as an
identity anchor. Clean FAX3B cases 200 and 389 have no mixed edge and are
unchanged by this probe; 373 remains upstream unsurfaced.

The local signal does not establish usable full-flight box coverage. On 164,
the later S3 source boxes widen and may include a background person. Sparse
target feature tracks survive into those boxes (e.g. 16/16 inside at frame
261), which supports branch identity but cannot certify box instance purity.
The sampled FAX3B flight anchors miss the four-frame asserted window, so
the measured nine-anchor flight coverage remains 0/9, as with V3. There is
no observed reduction in wrong-person continuation over V3's zero sampled
wrong-person links on this fresh authority. The method has no fresh
generalization result yet.

Higher-resolution source inspection confirms that the target and neighboring
person are visually distinct at frame 261, but the frozen S3 detector still
produces a broad box: full-frame 640 input width .506, 1280 input width .451
in proxy-normalized coordinates. A tighter 640 crop can produce width .291,
but that crop may truncate the target and is not an independently validated
person box. HQ recropping is not accepted as a box overlay solution on this
evidence. No appearance feature or instance segmentation result is accepted.

The next test is the blind FAX4 session-disjoint HUMAN queue. Its raw-only
selection and manifest were committed before opening S3/FSR outcomes. Until
that authority is sealed and the method is evaluated, full-action overlays
remain unsafe and Event Logic/pose stay frozen.
