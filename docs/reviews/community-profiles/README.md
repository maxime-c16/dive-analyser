# Profiles and discovery — PR 1 of 3

The Community page searches active members by display name or unique handle.
Visible linked diver names also match: searching Fanny finds the Fouiny account.
Selecting a result opens that member's profile, with their identity, bio,
profile photo, and a latest-first three-column dive grid. Tiles open the
existing Library player with its usual likes and comments. The previous
activity timeline remains available in the Activity tab.

## Visual evidence

These screenshots use the real **Fouiny** account (linked to **FANNY**) and
12 of its public dives, including their actual posters and playable previews.
They were verified in an isolated development database with a copy of the
public member/diver/dive records. The production account, videos, and access
rules were not changed. Source media and preview credentials are not committed.

- [Desktop search](desktop-search.png)
- [Desktop profile](desktop-profile.png)
- [Mobile profile](mobile-profile.png)
- [Existing player opened from a profile tile](mobile-player.png)

Verified at 1440 × 1000 and 390 × 844: all 12 posters load, the mobile grid
keeps three columns without horizontal overflow, and a tile opens a real
video whose playback clock advances. Browser execution raised no page errors.

## Deployment

Apply `backend/migrations/add_member_profiles.sql` against Postgres **before**
deploying this backend. It adds optional unique handles, bios, bounded avatar
storage, and avatar version timestamps. Existing accounts keep their names
and start with no handle/photo and an empty bio. Pillow decodes JPEG/PNG/WebP,
limits upload size/pixel count, resizes to 256 × 256, and strips metadata.

No nginx or Mac-worker changes are required. Deploy with the repository's
`ci/ship.sh` workflow after merge; this PR does not deploy production.

## Subsequent PRs

Start each only after review-bot approval of the preceding PR:

2. Shared mention autocomplete and clickable member identities, initially in
   dive comments, with access-aware notifications. Reuse member IDs and handles
   from this PR.
3. One-to-one inbox/conversations, text and dive cards, notifications, reactions,
   and acknowledged delivery/read receipts. Model conversations and participants
   so groups can be added later; group UI/membership is outside these three PRs.
