# Guest dive sharing

Owners can use **Share** directly below Comments in the dive player. The first
click creates and commits a unique capability, then copies the link. Subsequent
clicks in that player copy the same link. If clipboard access is denied or the
browser is on plain HTTP, the committed link appears for manual copying.
**Revoke shared links** invalidates every link for that dive. Reopening the
player checks for active links and exposes revocation without creating a new
capability.

Anyone holding the complete link can open the selected video without an
account. Links support multiple guests and remain valid until revoked, the
video is replaced, the dive is deleted, or the creating owner loses active
ownership. Sharing does not change library visibility, including private dives.

Guests get a randomly chosen French film-character name (for example Neville
Londubat or Severus Rogue). Their opaque HttpOnly cookie preserves that identity
for a year in the browser. Guests can like/unlike and add/delete their own
comments; guest and member discussion/counts are combined. Clearing cookies or
using another browser creates another identity. Guests receive no login,
workspace, library, editing or media-preparation permissions.

The link secret is in the URL fragment and is exchanged via `X-Dive-Share` for a
cookie-backed, per-share grant. Only SHA-256 hashes are stored. Video, social
and comment endpoints revalidate the grant and owner each time; IDs alone are
insufficient. Cookies use the existing `AUTH_COOKIE_SECURE` configuration.
Guest writes also use the existing same-origin check. Responses disable caching
and referrers. B2 uses verified production storage and short-lived presigned
playback; an already issued B2 URL can remain usable until its TTL expires.
Ready local video uses the existing safe-path and HTTP Range implementation.

## Deployment

Before deploying this feature to an existing database, apply
`backend/migrations/add_dive_sharing.sql` after `add_dive_social.sql`, using the
usual operator migration procedure. It adds shares, guest identities/grants and
likes, and extends comment authors without changing existing member data.
The SQL is safe to reapply. `ci/ship.sh` does not apply SQL migrations itself.

## Validation

- Guest API tests cover separate guests, returning identity, private video
  playback, Range, workspace denial, ownership, revocation/video replacement,
  deactivated owners, guest/member counts, author-only deletion, pagination,
  origin checks and B2 fallback/ambiguity.
- UI tests cover duplicate clicks, clipboard permission timing/failure,
  revocation, anonymous viewing and commenting, invalid links, and React
  StrictMode's effect replay without duplicate guest-cookie exchanges.
- PostgreSQL 16 migration was applied twice to an isolated Debian container,
  preserving existing reactions/comments and checking author constraints and
  cascading deletion.
