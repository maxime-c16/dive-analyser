# Administrator account design review

Start the development preview with `npm --prefix frontend run dev -- --host 0.0.0.0 --port 3016`.

Open `/e2e/fixtures/admin-account-studio.html` to review the actual production components with a synthetic API transport. Dive #700 demonstrates denied access, a real-component resolution preview, confirmation and an allowed recheck. Reload resets all demo writes. Direct tabs use `?section=profile|security|history|lifecycle`.

The original three-layout comparison remains at `/e2e/fixtures/admin-account-review.html?layout=access`. Access studio is the selected direction and the default. Identity, Security, Audit trail and Lifecycle are inline tab pages with the same card surfaces. Tabs support arrow-key navigation, browser back/forward and direct links such as `?layout=access&tab=security`; unsaved profile drafts survive tab changes.

Mobile uses stacked ownership cards, labeled capability cards in place of the desktop permission table, and a responsive tab grid. Change previews sit next to the ownership map on phones.

Other design references remain available:

- `?layout=command`: account command center, health summary, next actions and recent history.
- `?layout=support`: case-led investigation, account context, notes and resolution handoff.
- `?layout=access`: ownership graph, capability matrix, binding picker and change staging.

The preview runs on synthetic data and does not call any backend. All three designs support profile editing with failure/retry, private/public diagnostics, explicit ownership change previews, individual session revocation, audit filters, and the proposed suspension/recovery lifecycles. Changes update every view of the demo account. Reset restores the initial scenario; writes are in-memory and reset on reload. The directory intentionally keeps one editable scenario so comparisons remain equivalent.

Try competition access: run the investigator, preview a grant, inspect its viewing/editing/deletion consequences, confirm, rerun and inspect the audit trail. Public viewing must remain separate from management. Test failure should preserve the draft and allow retry.

## Implemented stack versus proposed UI

PR 1 implements account/profile/binding management and directory navigation. PR 2 implements session control and existing audit-history reads. PR 3 integrates the approved Studio layout, live ownership and dive totals, policy-backed diagnostics, binding impact previews and the inline account lifecycle page. Grants/removals recheck their preview before applying: changed impact returns to review, failed mutations retain the confirmation. Ownership pages are fetched through bounded APIs so links beyond the old 200-ID detail cap remain visible. Binding changes preserve other accounts and existing dive records. Counts describe authorization, including public viewing that survives removal; disabled accounts retain their links with zero effective access.

Case notes, durable before/after audit values, recovery invitations, account-health prioritization and scheduled restoration in the design lab are product proposals. These remaining proposals are not connected to production services and have no controls on the production page. In particular, no invitations are sent and no restoration scheduler runs. The production diagnostic checks authorization, not media readiness or provider availability.

## Validation

`node docs/reviews/admin-accounts/validate.cjs` runs browser flows for all three variants and checks each tab at 320, 360, 390, 430, 768 and 1440 pixels. It checks card bounds and clipped card contents, inline tab semantics, draft preservation, keyboard navigation, browser history and direct tab links. Optionally set `ADMIN_REVIEW_URL` to the review HTML URL. It saves screenshots outside the repository under `/tmp/admin-account-ui`; no video is recorded. The fixture is development-only and is excluded from the production router/build. Backend admin tests check account isolation, Origin guards, audit redaction, revocation idempotency and target-account authorization.

Production-component validation used the T3 collaborative browser: inline tabs and card clipping at 320, 390, 768 and 1440px; Studio bounds also at 360 and 430px; profile draft retention and save, denied → preview → grant → allowed, individual session revocation, suspend/restore, and audit events. Unit/API tests separately cover failed mutations, changed impact requiring reconfirmation, disabled targets, public/private counts, shared bindings and administrator guards. Full frontend suite: 387 passed. Production build and both fixture TypeScript checks passed. Full portable backend suite: 859 passed, 6 skipped, 23 performance tests deselected; final administration subset after the policy-count regression additions: 35 passed. Final affected frontend checks: 10 passed, including the added stale-diagnostic regression. The macOS host lacks `flock` for the gate wrapper; portable checks run directly.
