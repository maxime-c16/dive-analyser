# Judge Room MVP

Create a room from Evaluations, share `/room/:code`, and play with 1–8 humans.
Guests choose a nickname; authenticated participants join directly. The jury
fills to five seats with deterministic bots and, when opted in, Maxime's shadow.
Classic, Mole (including an honest panel), and Guess the Code are implemented.

Each round loads before playback: connected humans report `canplaythrough` over
the room WebSocket. All ready (or a 15-second timeout) schedules playback one
second later. Playback always starts at frame zero and runs once, full screen,
with the diver chip and no app navigation. The server opens a ten-second scoring
window after the known video duration or all connected clients report `ended`.
Guess the Code speed starts at that scoring boundary. No local replay control
is offered. The next video preloads during reveal and the same video element
is promoted into the following round.

The server owns deadlines, votes, points and transitions. WebSocket snapshots
carry a shared `starts` timestamp; clients play independent local copies. A
reconnect resumes the current round with the same room capability. Round scores
remain hidden until the deadline. Reveals drop the highest and lowest score.
Human ratings persist immediately, independently of a later disconnect. A
minimal result is saved at the end; active room state expires after six hours
and is lost when the single backend worker restarts.

Both judging and Guess the Code reuse the evaluation player with a room-scoped
transport, full-frame `contain` playback on black, and an avatar/name chip for
the actual dive's diver. Guess the Code hides the code and DD in server state
and video overlays; four choices come from the official DD reference for the
same group, height and platform. Correct answers earn more points when faster.

## Scope and limitations

- Echo ghosts are deferred. Bots and the opt-in shadow are implemented; human
  stored ratings and room ratings contribute to truth, bots never do. With no
  human truth available, bots use a neutral starting score and humans receive
  no closeness points. No DD or legacy performance label is treated as an
  official execution score. No official execution panel exists in current data.
- Playlists use public, attributed dives with ready cached playback. This is a
  conservative intersection of visibility for every possible guest. Private
  dives, even in the host's latest session, are excluded. Cold media is skipped.
- Only user 1 has enough history to supply a shadow in this MVP. The per-user
  permission is stored separately and can be changed on the create-room screen;
  migration seeds consent on only for user 1. Preference changes affect future
  playlist selections. Exact dive ratings take priority over the mean offset. A player’s own shadow
  is always excluded from their room’s panel.
- Invitations allow public poster previews, never anonymous playback. Joining
  issues an HttpOnly, SameSite room cookie; playlist media checks membership and
  current visibility on every request. It grants no workspace session.

## Deployment prerequisite

Apply `backend/migrations/add_judge_rooms.sql` manually **before** deploying
backend and frontend. Startup deliberately does not create these tables.
Server SQL migrations are not applied automatically. There is no Mac service
change. This PR must not be merged or deployed by the implementation agent.

## Validation and screenshots

Backend tests cover lifecycle/deadlines, deterministic ghosts, consensus and
leave-one-out helper, points/streaks, mole assignment, guest scope, persistence,
visibility revocation, room capacity, CSRF, shadow preferences, Guess the Code
and WebSocket rejoin. Existing visibility and evaluation-request tests also run.
The full frontend suite (812 tests) and TypeScript check pass. The follow-up
backend/regression selection passes 47 tests; PostgreSQL migration parity also
passes against a separate disposable database (30 calendar/PostgreSQL tests).

Screenshots are of the real application against a local backend with public
production preview clips and fixture players/ratings, not the deleted mockup.
A two-browser run exercises guest join, both scores, timed reveal, all rounds,
mole vote, results and replay. A separate run verifies Guess the Code, the
visible diver chip, hidden code and computed `object-fit: contain`.

| Screen | Screenshot |
| --- | --- |
| Invitation | [mobile](join-mobile.png) |
| Lobby | [mobile](lobby-mobile.png), [desktop](lobby-desktop.png) |
| Full-screen playback | [mobile](judging-mobile.png) |
| Scoring after playback | [mobile](scoring-mobile.png) |
| Reveal | [mobile](reveal-mobile.png) |
| Mole ballot | [mobile](mole-mobile.png) |
| Results | [mobile](results-mobile.png) |
| Guess the Code | [mobile](guess-code-mobile.png) |

## Mobile follow-up verification

The room owns a safe-area `100dvh` viewport, including lobby, reveal, ballot and
results. The lobby playlist is one horizontal strip. Actual two-browser runs
on the provided local stack cover 390×844 and 320×568; `*-fit-390.png` and
`*-fit-320.png` show each phase. The tests delay the second browser’s first
video and assert the room remains in loading with no start/scoring deadline.

For a direct uvicorn + Vite development stack, run the backend with
`MEDIA_XACCEL_ENABLED=false`: Vite does not implement nginx’s internal
`X-Accel-Redirect` byte serving. Production nginx continues using acceleration.
No additional SQL migration or test-database edits are needed for this follow-up.

[Two-browser mobile verification log](mobile-verification.txt) records the
ready gate and viewport bounds. The full follow-up game uses a one-dive playlist
selected through the real “Par code” UI, then replays in Guess the Code.
The default eight-dive lobby is captured before that selection.
