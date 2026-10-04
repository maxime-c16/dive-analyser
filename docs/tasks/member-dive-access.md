# Member dive ownership and visibility

Public means visible to every signed-in member; anonymous access is denied.
New dives default to public. Private dives are visible only to accounts with
an explicit OWNER binding to their diver. Ownership never follows display names.
Administration is separate from dive ownership. Comments are the next phase.

## Tasks

- [x] Add dive visibility and explicit administrative capability, with idempotent SQL migration.
- [x] Provision a new diver identity for new members; preserve verified bindings for existing divers.
- [x] Centralize visibility across API queries, derived data, media and caches.
- [x] Enforce ownership for dive writes and protect shared session/system operations.
- [x] Replace global-primary “My dives” scoping with current-account bindings.
- [x] Add owner editing/deletion and public/private controls to the clip viewer.
- [x] Verify with multiple isolated accounts, including guessed IDs and visibility changes.
- [ ] Run local tests, server pre-push checks, then create and merge a green PR.

## Delivery boundaries

Existing attributed dives backfill to public. Unattributed dives backfill to
private and remain manageable by administrators until an operator verifies ownership. Existing owner accounts gain the
explicit administrative capability; invited members do not. Legacy role strings
remain compatible, but do not grant dive ownership. Private dive metadata and
media must also disappear from derived summaries and cached analytics.

SQL migrations are manually applied during deployment per docs/REPO_WORKFLOW.md.
This task authorizes testing, pushing, PR creation and merging; deployment is a
separate step. Already-issued object-storage playback links can remain valid
until their short expiry.

## Community roadmap

1. Timestamped dive comments: click a timestamp to pause at that moment; replies and editing/deleting your own comments.
2. Simple reactions (👏, 🔥, 💪) with member names.
3. In-app notifications that open the exact dive and conversation.
4. Feedback requests with a question and helpful-reply marking.
5. Member profiles: display name, avatar, optional background and shared dives; viewers remain full members.
6. Friends activity: recent shared dives, feedback requests and milestones.

Each interaction must reuse dive visibility and membership checks. Community
participation grants no permission to edit/delete another member's dive.

## Validation before PR

- Local backend: 741 passed, 6 skipped (portable suite; performance tests excluded).
- Local frontend: 132 passed, TypeScript and production bundle pass.
- PostgreSQL migration: applied twice to isolated fixture tables in a transaction;
  owner/admin backfill, attributed-public/unattributed-private backfill, and
  invalid visibility rejection passed. Transaction rolled back completely.
- Browser: synthetic Alice/Bob/viewer accounts; My dives scope, compact immediate
  visibility change, owner notes editing, hidden management on others' public
  dives, and a direct unauthorized write returning 403.
- Existing server data audit: both accounts have explicit OWNER bindings;
  all 2,865 dives are attributed. No ownership reassignment was necessary.

Production must keep USER_AUTH_ENABLED=true. Existing verified bindings are
preserved; registration creates a unique diver identity instead of claiming a
matching display name. Legacy aggregate psychology and operational sync remain
administrative until they have account-specific resource contracts.
