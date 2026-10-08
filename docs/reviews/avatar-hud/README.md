# Profile photos and HUD variants

This branch stacks on PR #91 (`t3code/community-profiles-messaging`). It reuses
that PR's authenticated, bounded upload API and deferred 256×256 JPEG storage.
No extra photo storage, public image endpoint or media-worker service is added.

## Compare the three versions

Run `npm --prefix frontend run dev -- --port 3011`, then open
`http://localhost:3011/avatar-lab.html`.

The development-only entry point renders the production `MemberAvatar` component.
Orbit is a light segmented ring; Reticle (default) adds analysis-camera corner
brackets; Depth uses an angular frame and ruler ticks. Select a frame to compare
profile, comment/activity and an explicitly labeled future-DM example. Test
28/36/48-pixel sizes, initials, light/dark themes and a local photo. The lab never
writes an account or uploads its sample picture. Its SVG illustration is a fixture.
Vite's production build only includes the normal application entry point.

The shared avatar is used in community cards, member profiles, Account, the
sidebar, admin account headers, comment/reply threads and activity rows. The
server identity contract is `avatar_url` + `avatar_hud`; future DMs should use
these fields and `MemberAvatar`, rather than storing a copy of the photo on each
message. DMs themselves are not implemented in this change.

## Manage a photo

Account and the member profile editor share `AvatarManager`: add/replace/remove
photo, choose a persisted HUD, report loading/error/success, reject invalid or
oversized input before transport, and retain initials for missing/broken photos.
Photo replacement changes the URL version on all newly read identities, including
old comments and activity. Removal keeps the user's HUD preference. Photo bytes
are never sent in identity responses; guest share pages retain initials.

## Deployment

Merge PR #91 first, then this branch. Before deployment, apply
`backend/migrations/add_member_profiles.sql` (PR #91) and
`backend/migrations/add_avatar_hud.sql` against Postgres, in that order.
These SQL migrations are manual per `docs/REPO_WORKFLOW.md`. Both backend and
frontend services are required. No Mac-worker upgrade is needed.

## Verification

Frontend regression suite, production build, backend API regression tests, and
release-note validation. The collaborative browser verified frame switching,
loaded illustrations and responsive width at desktop and 390px. Screenshot
capture was attempted repeatedly but the preview client returned an execution
error; no visual screenshot artifact is claimed.
