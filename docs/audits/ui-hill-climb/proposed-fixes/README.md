# Prepared fixes, not applied to the reviewed candidate

Base6cb6cff77907e59e809c5f4197a0e107d75ebaf4. Source remains frozen while Sol and Opus review it.

1. Confirmed empty By-code form: style/label the input as Dive code, show an example, disable empty submission, label Apply code. Before: ../round-04/images/by-code-before-crop.png. Candidate patch prepared; no AFTER screenshot yet and no fixed-score claim.
2. Room footage caveat: primary room media may redirect to an external light derivative. Existing fetch failure falls back to the same URL; proposal retries the already-supported room-scoped ?q=preview path before retaining streaming fallback. Authorization and backend are unchanged. Unit regression prepared; actual playback/network reproduction remains required before adopting this fix.

Patch applies only after current reviewers finish; new commit and fresh councils required. Test copy under /tmp/dive-ui-next-candidate is separate from served source. No live directories or authentication modified.

## Sol medium additions (minimum4,55low cells)

3. Expanded analysis inventory renders all409 rows in a long page. Prepare20-row client pagination without changing statistics, charts or the complete drawer sequence. Regression test traverses all130fixture attempts and opens the final exact attempt. Move What changed into the existing secondary disclosure, align panel radii.
4. Calendar new-form Save/Discard below initial viewport: prepare a sticky form header containing the existing actions, preserving dirty confirmation and submit validation. No save performed in browser.
5. History secondary identity text remains small in broad rows: prepare14px metadata and16px identity, retaining intentional scorecard artwork.

Prepared bundle42existing targeted tests passed in the isolated copy. New pagination regression and typecheck run separately. None of these proposed fixes is served, committed, visually verified or design-scored yet. Wait for Opus result before replacing candidate; then real five-size BEFORE/AFTER and fresh councils required.
