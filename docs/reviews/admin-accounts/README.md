# Administrator account design review

Start the development preview with `npm --prefix frontend run dev -- --host 0.0.0.0 --port 3016`.

Open `/e2e/fixtures/admin-account-review.html`. Direct comparisons:

- `?layout=command`: account command center, health summary, next actions and recent history.
- `?layout=support`: case-led investigation, account context, notes and resolution handoff.
- `?layout=access`: ownership graph, capability matrix, binding picker and change staging.

The preview runs on synthetic data and does not call any backend. All three designs support profile editing with failure/retry, private/public diagnostics, explicit ownership change previews, individual session revocation, audit filters, and the proposed suspension/recovery lifecycles. Changes update every view of the demo account. Reset restores the initial scenario; writes are in-memory and reset on reload. The directory intentionally keeps one editable scenario so comparisons remain equivalent.

Try competition access: run the investigator, preview a grant, inspect its viewing/editing/deletion consequences, confirm, rerun and inspect the audit trail. Public viewing must remain separate from management. Test failure should preserve the draft and allow retry.

## Implemented draft stack versus proposed UI

Draft PR 1 implements account/profile/binding management and directory navigation. Draft PR 2 implements session control and existing audit-history reads. Draft PR 3 implements policy-backed dive access diagnostics and this design lab. The selected design still needs production integration before merge.

Case notes, durable before/after audit values, recovery invitations, account-health prioritization, dive-count impact previews and scheduled restoration in the design lab are product proposals. They are not connected to production services in this stack. In particular, no invitations are sent and no restoration scheduler runs. The production diagnostic checks authorization, not media readiness or provider availability.

## Validation

`node docs/reviews/admin-accounts/validate.cjs` runs the desktop/mobile browser flows for all three variants. Optionally set `ADMIN_REVIEW_URL` to the review HTML URL. It saves screenshots outside the repository under `/tmp/admin-account-ui`; no video is recorded. The fixture is development-only and is excluded from the production router/build. Backend admin tests check account isolation, Origin guards, audit redaction, revocation idempotency and target-account authorization.
