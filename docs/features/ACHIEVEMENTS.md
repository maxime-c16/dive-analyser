# Member achievements

Members unlock achievements from real actions (profile photo, first comment,
first message, judging a dive...). A toast celebrates each unlock and the
profile has an **Achievements** tab (`/users/:id?tab=achievements`).

## How it works

- Catalogue and rules: `backend/app/services/achievements.py` (`RULES`). Every
  rule is a monotonic count against a target, evaluated from the live tables.
  Re-evaluating can only add unlocks, so deleting a comment never revokes
  "First comment". Counts give progress bars for free.
- Ledger: `user_achievements (user_id, key, unlocked_at, seen_at)`.
- Triggers: write endpoints call `achievements.award(db, user_id, <trigger>)`
  after their own commit (profile, avatar, like, comment, message, rating,
  evaluation request, share). It never raises. Likes/comments *received* are
  evaluated for the dive owners (`award_dive_owners`).
- API (`backend/app/api/v1/achievements.py`): `GET /users/me/achievements`
  (full catalogue, backfills), `GET /users/me/achievements/unseen` (toast poll;
  backfills once for a member with no rows), `POST /users/me/achievements/seen`,
  `GET /users/{id}/achievements` (unlocked only: locked entries and progress
  stay private).
- No inbox notification on purpose: a like or comment still emits nothing to
  the dive owner's inbox. Delivery is the toast.
- Frontend: `AchievementToaster` (mounted in `App.tsx`) polls `unseen` on load,
  focus and every minute, and `installAchievementProbe` (called in `main.tsx`)
  triggers a debounced re-check after any successful non-GET `/api/v1` write.
  Texts live in `achievements.*` in both locales.

## Adding an achievement

1. Add a `Rule` in `RULES` (reuse a trigger, or add one and call `award` from
   the endpoint that causes it).
2. Add its icon in `achievementCatalog.ts` and `achievements.items.<key>` in
   `en.ts` and `fr.ts` (the parity test enforces both).
3. Existing members get it on their next visit to the Achievements tab.

## Deploy

Run `backend/migrations/add_user_achievements.sql` on the server **before**
deploying the backend (`ship.sh` does not apply it).
