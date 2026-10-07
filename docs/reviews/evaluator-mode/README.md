Visual review notes — evaluator mode (issue #68).

Fixture-driven browser review (synthetic media, no production data), done with
headless Chromium against the real `/evaluations` route in the fr locale.
Screenshots here were captured at mobile 390×844 (portrait 720×1280 source),
landscape 844×390 (1280×720 source) and desktop 1440×1000:

- `mobile-judging.png` — full-viewport stage, top HUD (quit, diver name,
  code/height, counter badge, prompt fold), controls rail top-right, score
  dock bottom (stepper + choose placeholder + Pass/Confirm).
- `mobile-reveal.png` — peer cards flip in then the own "Vous" card arrives
  once; names under each card; compact chips + primary Next.
- `mobile-summary.png` — session recap (rated dives with notes, passed list)
  with Évaluer encore / Faire évaluer un plongeon CTAs.
- `mobile-history.png` — Mes jugements with the retained jury panel.
- `landscape-*.png` — video keeps the full stage height; the dock becomes a
  translucent right column; controls rail and score card never overlap.
- `desktop-*.png` — video full stage; dock bottom; width-borderless contain.

Recorded intro choreography v2 (card-game direction, ~3.2s at 60fps recording,
compositor-driven at any refresh rate incl. 120Hz/VRR):
- `intro-mobile.webm` (390×844), `intro-landscape.webm` (844×390),
  `intro-desktop.webm` (1440×1000) — pile of four card BACKS → curved deal
  with a damped overshoot into a readable four-card fan → successive true 3D
  flips revealing the decorative faces (all readable by ~1.9s) → fan tighten
  at 2.2s → travel/shrink into the measured HUD score-card zone, fading only
  at the very end. Every keyframe time is defined in absolute milliseconds;
  all four card rects stay inside the stage during deal/read/merge at 390,
  320, 844 and 1440 widths (`/tmp/eval-intro-bounds-v5/bounds.json`); no
  dark veil, decoration pointer-transparent, Skip accessible, reduced-motion
  ends immediately, judging interrupts the decoration instantly.

Asserted checks (no-force pointer interactions only):
- zero overlap between the playback control rail and the score card;
- header stays single-row and the 6-char diver name is not truncated;
- landscape Confirm reachable by a normal click at 844×390;
- reveal shows exactly len(ratings) cards (own card deduped, named);
- batch retries return the same served batch; the next batch uses a fresh id;
- 503 vote failure keeps the chosen score and comment, retry succeeds;
- Mes jugements renders the retained panel (names + comments) after closure.

These PNGs contain only synthetic review fixtures.
