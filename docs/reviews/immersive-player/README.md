# Immersive dive player review

The 16:9 review container made a portrait dive occupy only a small strip of an iPhone screen. Review now uses the video's actual aspect ratio: full viewport with overlays on mobile, a centered tall video on tablet, and a tall video next to metadata/discussion on desktop. Existing dark slate panels, monospace dive codes and teal accents are retained.

| Layout | CSS viewport | Screenshot | Screen recording |
| --- | --- | --- | --- |
| Mobile | 390 × 844 | [Mobile](mobile.png) | [Mobile MP4](mobile.mp4) |
| Tablet | 768 × 1024 | [Tablet](tablet.png) | [Tablet MP4](tablet.mp4) |
| Desktop | 1440 × 900 | [Desktop](desktop.png) | [Desktop MP4](desktop.mp4) |

Additional screenshots: [mobile comments](mobile-comments.png), [mobile details](mobile-details.png), [tablet comments](tablet-comments.png), [desktop comments](desktop-comments.png).

## Interactions

Muted inline autoplay and looping; tap to pause/resume; double tap to like (never unlikes); hold for 2× and restore the selected speed on release/cancel; vertical swipe for previous/next within the current filtered Library; tap or swipe up on the description for details; comments drawer; dismiss with close/backdrop/Escape. Explicit seek, sound, playback, speed and previous/next controls support users who cannot use gestures. Desktop retains Shift+Left/Right navigation. Embedded analysis/session players retain native controls.

Likes and comments persist server-side. Only signed-in viewers who can see a dive can interact with it. Public-to-private changes immediately restrict discussion access. A user can remove their own comment; an administrator can moderate. Comments are limited to 2,000 characters and paginated in batches of 50. Existing ownership, editing and visibility controls remain in the details panel.

## Evidence scope

Captured using T3 Code's collaborative browser with responsive Chromium viewports. The standalone development fixture uses real local portrait diving footage, and explicitly mocked account/social data. Metadata is illustrative, rather than the source clip's real dive identity. The source footage is not committed; only the requested screenshots and recordings are included. Pointer events for double tap, long press and swipe in the mobile recording are synthesized through the browser's page evaluator because preview automation exposes clicks but no hold/swipe primitive. Actual gesture arbitration is also covered by unit tests.

These are three responsive layouts of the same implementation, awaiting visual review. Physical iPhone Safari (including address-bar changes, safe areas and the on-screen keyboard) still needs device acceptance testing. No production deployment or database migration was performed.

## Validation

- Frontend: 136 tests passed; TypeScript and production build passed.
- Backend: 36 tests passed across `test_dive_social.py`, `test_member_dive_visibility.py` and `test_friend_access.py` (real sessions, visibility, persistence, author-only deletion, validation and pagination).
- Browser: autoplay/mute, tap playback, double-tap like, 2×/restore, swipe, comments posting, details, Escape, backdrop dismissal and focus return checked. No horizontal overflow at 320×568, 844×390 or 1024×768.
- `git diff --check` passed.
- The repository's `ci/gate.sh fast` wrapper could not run on this Mac because `flock` is missing; its “another CI gate is running” output is a misleading consequence of that missing command. The checks above ran directly.

## Local review

Run `npm run dev` from `frontend/` and open `/e2e/fixtures/player-review.html`. Supply a local portrait H.264 video as `frontend/public/player-review.mp4` (gitignored). This fixture is not imported by the production entrypoint and cannot run in production mode.

## Deployment prerequisite

Apply `backend/migrations/add_dive_social.sql` before deploying with `ci/ship.sh`; SQL migrations are not applied automatically by the deployment workflow. The migration creates only the reactions/discussion tables. Follow `docs/REPO_WORKFLOW.md` for the normal branch/PR/master deployment process.
