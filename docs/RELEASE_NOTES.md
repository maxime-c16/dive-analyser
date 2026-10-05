# What's new

Each user-visible PR includes a JSON file under `backend/release-notes/`, named
after its stable, unique `id`. The agent writes it alongside the code, before
review. For internal-only work, put `Release notes: none — <reason>` in the PR
description. CI validates the schema and refuses edits to existing notes.

```json
{
  "id": "browser-video-import",
  "date": "2026-10-05",
  "title": "Add videos from your browser",
  "body": "Select several clips and save them straight to your library.",
  "audience": "all",
  "components": ["frontend", "backend"]
}
```

`title` is at most 100 characters, `body` at most 600. Text is rendered as plain
text. `audience` is `all` or `admin`; the authenticated backend filters admin
notes. `date` is the note's date, not a guaranteed deployment date.
`components` lists the server services needed by the feature (`frontend`,
`backend`, or both). A note becomes eligible only when its introducing commit
is an ancestor of every listed service's running image SHA. Worker-only changes
are currently silent: do not announce a feature depending on a Mac upgrade
until that upgrade is confirmed, then add its note in a server PR.

`ci/ship.sh server --dry-run` prints the planned catalog, accounting for partial
deployments. A normal successful deployment publishes the latest 100 eligible
notes into the backend's existing persistent media-cache volume, after all
health checks. Transfer is staged and atomically renamed. A publication failure
fails the deployment and restores the previous images, leaving the previous
catalog intact. Explicit rollback recomputes eligibility from the services that
actually run. No Compose changes or SQL migration are needed. `--force` produces
the same note IDs and does not create another announcement.

The UI polls the authenticated `/api/v1/updates` once a minute while visible,
and on focus. It groups unseen notes into one hint and durably claims a
24-hour cooldown before display. Closing the hint remembers only its captured
IDs. New arrivals do not modify an open panel. Seen IDs and cooldown are keyed
by account in local storage and synchronized across tabs; Web Locks serialize
the display claim. If storage or Web Locks are unavailable, automatic hints
are suppressed and manual history remains usable. State is per browser, not
cross-device. Playing videos and existing dialogs suppress automatic hints.

The navigation's What's new button always opens history manually. The panel
closes with its cross, Escape, backdrop, or return button, traps keyboard focus
and restores it on close. Missing/corrupt manifests and API errors stay quiet.
An older frontend tab must reload voluntarily before reading a catalog tied to
a newer frontend SHA; no automatic reload interrupts playback.

Validation: `python3 ci/release-notes.py validate`, gate regression tests,
backend authentication/filtering tests, frontend persistence/grouping tests,
and the standard CI gate. Historical design explorations live in
`docs/reviews/whats-new/`; their HTML is a visual mock, not the production UI.
