# Notification preferences backend sync

Account page notification settings are currently device-local only and
drive nothing. Wire them into the app with a per-account backend store.

## Current state

- `frontend/src/pages/Account.tsx` stores three toggles in
  `localStorage['dive-analyser.prefs.v1']` via `usePrefs()`:
  `emailNotifications` (default true), `milestoneAlerts` (default true),
  `weeklyDigest` (default false).
- No backend prefs endpoint exists. Grep confirms zero consumers outside
  `Account.tsx` + `Account.test.tsx`: no email sender, milestone logic, or
  digest job reads these values.
- UI already discloses this: "Stored on this device until account sync lands."

## Tasks

- [ ] Add per-account notification preferences store with idempotent SQL migration
  (new table or `user_auth` columns: `email_notifications`, `milestone_alerts`,
  `weekly_digest`, all boolean with current frontend defaults).
- [ ] Add authenticated `GET` + `PUT /api/v1/account/preferences` (session cookie,
  `AuthGuard` semantics; per-account scoping, no IDOR; validate booleans only).
- [ ] Update `usePrefs()` to load from backend on mount, fall back to
  `localStorage` on failure/offline, and write-through on toggle (optimistic
  UI, revert on 4xx/5xx).
- [ ] Keep `localStorage` as offline fallback keyed per account once sync lands
  (avoid leaking one account's prefs to the next login on a shared device).
- [ ] Consume prefs where they matter, or remove dead toggles:
  `emailNotifications` gates milestone/shared-dive comment emails (when they exist),
  `milestoneAlerts` gates in-app milestone alerts, `weeklyDigest` gates the
  Monday digest job. Until a sender exists, prefs are stored but inert.
- [ ] Tests: backend per-account isolation (Alice/Bob cannot read/write each
  other's prefs, anonymous 401); frontend sync + fallback + offline behavior.
- [ ] Run local tests, server pre-push checks, then create and merge a green PR.

## Delivery boundaries

Follows `docs/REPO_WORKFLOW.md`: branch off `origin/master`, PR, merge.
SQL migration under `backend/migrations/*.sql` is applied by hand during
deployment (no runner) — PR description must note the manual step per the
review contract.

Related community roadmap (`docs/tasks/member-dive-access.md` item 3):
in-app notifications that open the exact dive and conversation. This task is
the prefs prerequisite, not the notification center itself.
