# Account administration: three PRs, highest gain first

Three stacked draft PRs. Merge order is 1 → 2 → 3. UI direction remains open until the three interactive layouts are reviewed. All layouts use the same components and workflows; review fixtures use synthetic data and never enter the production router.

1. **Account workspace and binding QOL.** Dedicated administrator route; account header; profile editing with Save/Discard and navigation protection; searchable, linked-first bindings with explicit ownership consequences; paginated directory and preserved URL filters. Highest gain: faster, safer daily account editing.
2. **Security and accountability.** Paginated, account-scoped audit history and individual live session revocation; existing password reset and sign-out-all actions with explicit impact confirmation. Highest gain: explain changes and resolve account-security incidents using existing tables.
3. **Access troubleshooting.** Read-only dive visibility and management diagnostics using the production authorization policy; copyable support summary; three development-only layout alternatives and a LAN review URL. Highest gain: explain access without impersonation or changing permissions.

Layouts: A — focused horizontal tabs; B — persistent section sidebar; C — overview-first cards with section shortcuts. Compare profile save/discard, search/add/remove binding, session revoke, history, and access check in every layout. Validate desktop and narrow mobile widths, keyboard focus, error recovery, and no console errors.

Follow-ups, deliberately outside these three initial PRs: email delivery and recovery links, MFA, delegated administrator roles, temporary grants, timed suspension, account merging, stored support notes, and impersonation. These need distinct lifecycle/security decisions; no nonfunctional controls are exposed for them.
