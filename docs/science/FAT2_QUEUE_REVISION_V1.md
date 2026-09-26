# FAT2 queue revision V1 (post-annotation record)

The committed queue (`FAT2_ANNOTATION_QUEUE_V1.md`) specified dives
1190/s75, 1279/s80, 2838/s202. Outcome:

- 1190, 1279: fully labeled (takeoff, water contact, apex + independent apex
  repeat; flight/prep/post boxes + one blind repeat). Apex repeat agreement
  0.033 s (one frame) on both dives.
- 2838: **annotator-excluded as HUMAN_UNLABELABLE** ("cannot reliably see
  the diver", 2026-09-26T23:10:38Z). Raw-clip review corroborates: the 18.6 s
  proxy is mostly empty pool/deck; any dive figure is too small/distant to
  annotate reliably. No same-session backup exists, so no swap was possible.

Authority frozen as `FULL_ACTION_GT_HUMAN_V2_FRESH` (48 items + FAT2_EVENTS,
digest `74aaf4ad29e00180f5893a0c43bba10bc1dac3a323f758539395a9f2ea914592`,
exclusion recorded in MANIFEST). 2838 stays in the funnel denominator as
unlabelable. The predeclared 3-dive gate is therefore evaluated on 2 dives;
all denominators below are explicit.
