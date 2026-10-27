# Photos cleanup: exploratory Mac experiments

Historical checkpoints, not the operational contract. The current implementation
and activation procedure are in [PHOTOS_CLEANUP_PERMISSIONS.md](PHOTOS_CLEANUP_PERMISSIONS.md).
The dated VNC/UI diagnostic scripts were superseded by the integrated runner.

Checked on 2026-10-27 on mac-media-01 (macOS 15.1.1), GUI user
`divesensei`, uid 501. The initial authorization preflight changed no assets;
later sections record synthetic deletion tests.

## Observed authorization

The deployed agent starts via `DiveSensei Python Runtime.app`
(`com.diveanalyzer.python-runtime`), which launches the media-node venv Python.
The app already declares `NSPhotoLibraryUsageDescription`.

`ops/photos-permission-preflight.py --request` was run by a one-shot Aqua
LaunchAgent using that same venv Python and associated bundle identifier.
PhotoKit `authorizationStatusForAccessLevel_(PHAccessLevelReadWrite)` returned
`authorized` both before and after. No permission dialog was needed.

This proves read/write authorization for the probe context. It does not prove
unattended deletion works, or that every future process identity inherits the
grant. The production wrapper itself was not changed or restarted.

The probe and result are retained outside the deployed code directory at:
`/Users/Shared/services/data/diveanalyzer/state/photos-permission-preflight/`.
The transient launchd service was unloaded after completion.

## Implemented behavior

`dual_write.photos_cleanup_mode` is `off` by default. `dry_run` prepares a
report without removing anything; `delete` requests removal in batches of
at most five clips. Both enabled modes require continuous ingestion and an
explicit `photos_cleanup_keeper_diver_id` identifying the active primary
diver on the server. They never scan historical ingests or the Photos library.

```yaml
dual_write:
  enabled: true
  continuous_new_ingest: true
  # Keep the existing B2 credential and ingest settings.
  photos_cleanup_mode: dry_run
  photos_cleanup_keeper_diver_id: 1  # replace with the verified primary diver id
```

The server and Mac must both ship this change via `ci/ship.sh` (dry-run
first); no SQL migration is required. Production configuration has not been
changed by implementation or canary testing. Start with `dry_run`, inspect
`<object_store.state_dir>/photos_cleanup/pending/*.json` for `would_remove`,
then switch to `delete` only after checking the keeper id and report. Setting
the mode back to `off` stops new cleanup requests and preserves pending reports;
an already submitted native request may still complete.
Reports/receipts stay private on the Mac; never commit them to the repository.

The normal new-ingest path takes a fresh Photos export in an isolated
directory when cleanup is enabled. Adjusted clips require the edited export
and a readable edit recipe; an original or stale vault copy cannot authorize
cleanup. A guard binds the Photos modification date, caption/edit hashes and
exported byte SHA to the staged upload. Any mismatch keeps the Photos asset.
The fallback ingestion path remains available, but cannot arm cleanup.

After full remote byte verification and successful server commit, eligible
assets enter the pending queue. A separate loop checks up to five entries
every five minutes. The authenticated server check confirms the local asset
mapping, primary keeper, single other active diver, current metadata/revisions,
committed ledger and verified production B2 location. Own/unknown/group clips
are kept. A transient failure is retried; an edited clip is never removed on
the basis of the old receipt. PhotoKit rechecks asset versions inside the
native change block. Native removal runs in a bounded child process, so a
confirmation dialog cannot block metadata sync or media ingestion.

## Real Mac canary results (2026-10-27)

Two separate one-second blue videos were created solely for this test with
`ops/photos-cleanup-canary.py`. Maxime accepted the macOS removal confirmation
on both attempts. The first asset was independently absent from PhotosDB
afterward; the second completed through the bounded subprocess adapter and
its manifest reports `removed: true`. No personal asset was targeted. The
test manifests and logs are retained in
`state/photos-cleanup-canary-20261027/`; transient test services were unloaded.

**PhotoKit read/write authorization is persistent, but the deletion confirmation
was repeated for the second request. Read/write access alone does not provide
zero-click cleanup.** The UI experiment below subsequently automated a test click.
The implementation groups clips into one native request (at most five assets),
so there is one confirmation per processed lot rather than per clip. If it
is not accepted within the helper deadline, the queue remains pending and
will be revalidated before a later attempt. Recently Deleted is not emptied.

The osxphotos author also documents that deletion through PhotoKit prompts
the user and that no bypass is known:
[deletion discussion](https://github.com/RhetTbull/osxphotos/discussions/1650).
Direct SQL modification of Photos.sqlite is not implemented: the local
catalog is not a supported deletion/synchronization interface.

## UI scripting experiment (successful isolated canary)

The user subsequently authorized testing AppleScript UI automation of the
native confirmation. The first background Python/osascript probe timed out
without a visible prompt. The installed Python Runtime bundle has no
`NSAppleEventsUsageDescription`; it was not modified.

A separate ad-hoc-signed script app, **DiveSensei Photos UI Test**, was prepared
under `state/photos-ui-canary-20261027/` with its own bundle identity
`com.diveanalyzer.photos-ui-test` and Apple Events usage description.
Maxime accepted its System Events Automation grant, then enabled Accessibility
for the same app. A new probe returned `ui_enabled=true`.

The deletion confirmation belongs to `UserNotificationCenter`, not the Python
request process. Its accessible heading was empty; its body explicitly described
deleting one video from iCloud Photos, with exactly two buttons, `Don’t Allow`
and `Delete`. The first inspection attempt exceeded the native helper deadline;
the stale test confirmation was dismissed using `Don’t Allow` before retrying.

The successful attempt first verified there were zero confirmation windows,
then launched a new native request restricted by the synthetic manifest.
`ops/photos-ui-canary-confirm.applescript` checked the live canary process,
exact window count, heading, body and buttons, then clicked `Delete`.
The native request completed and the manifest records `removed: true`.
A separate PhotosDB query confirmed zero visible assets for the fixture UUID.
The test app then refused a negative control using PID 1 (`Wrong canary process`).

The third disposable video and all test logs are recorded in
`state/photos-ui-canary-20261027/`; no personal media was targeted. Test services
were unloaded afterward, and the app task was reset to a read-only permission
probe. Its grants remain available for further testing.

This proves an unattended UI click in the open GUI session after manual grants.
It does not test reboot operation, localized prompts, or production batch
confirmation. The locked-session experiment below failed. The system window
exposes no requesting PID and the heading
was blank: the isolated canary relies on a zero-dialog baseline, one known live
request and one exact expected dialog. The canary script is **not wired into
production cleanup**. Production integration needs a reliably identifiable
requester, serialized requests and fail-closed matching before enabling it.
`ops/photos-ui-canary-inspect.applescript` is a syntax-checked, read-only process
inspector; it performs no clicks. No production worker or configuration changed.

### Screen Sharing disconnected / session locked

At the user's request, a fourth disposable video was created for a test after
Screen Sharing was closed. TCP port 5900 had zero established connections;
Quartz reported `CGSSessionScreenIsLocked=true` and login complete. These
conditions remained true at the independent check after the attempt.

The granted UI app still reported Accessibility enabled. Its baseline had
zero UserNotificationCenter windows. After the known native deletion request,
the automatic click correctly refused: `Expected exactly one test confirmation`.
A separate UI query again found zero confirmation windows. PhotoKit timed out,
and a separate PhotosDB check found the synthetic asset still visible.
No actual confirmation click or deletion occurred in this attempt.

The manifest `manifest-no-screen-sharing.json` and `noscreen-result.json` are
retained under `state/photos-ui-canary-20261027/`. The native request service
was unloaded and no auto-click task remained armed. The user then reopened
Screen Sharing and unlocked solely for cleanup. The stale test dialog was
cancelled, a fresh request targeted only the recorded fixture, and the guarded
AppleScript clicked Delete successfully. PhotoKit confirmed it absent and the
manifest now records `removed: true`. The cleanup service was unloaded and the
test app task restored to its read-only probe. This cleanup was not a repeat
of the disconnected-session experiment.

Conclusion: the tested automation fails with Screen Sharing disconnected **and
the session locked**. Disconnection alone with a still-unlocked session has not
been isolated. Do not promise unattended locked-session Photos deletion.

### Attempt to preserve an unlocked session on disconnect

The next step explicitly ruled out idle sleep as the cause. After Maxime
unlocked the desktop, Quartz reported unlocked with one TCP 5900 connection.
A temporary Aqua `caffeinate -d -i -u -t 300` process asserted UserIsActive,
PreventUserIdleDisplaySleep and PreventUserIdleSystemSleep. No permanent
authentication or screen-lock setting was changed.

The local Screen Sharing client was inspected through its UI. Its menu contains
`Connexion > Fermer`; the displayed app settings offered no leave-unlocked
option. Closing the connection with that command immediately produced zero
5900 connections and `screen_locked=true`, while the caffeinate assertions
were still active. The unlocked/no-viewer precondition therefore failed and
the prepared native deletion test was not launched.

After the connection reopened, Maxime confirmed he had manually entered the
password to unlock. Reconnection alone has not been shown to unlock the Mac.
The fifth synthetic fixture (`manifest-awake-no-sharing.json`) was then deleted
solely for cleanup via the guarded UI script and native absence verification.
All temporary awake/create/cleanup services were unloaded and the app restored
to its read-only probe. `ops/photos-ui-session-state.py` retains the read-only
Quartz/VNC check used for this experiment.

### Native authenticated loopback VNC experiment

The next user-authorized step tested real account authentication without
typing into the lock screen. The server advertised RFB 3.889 with security
types 30, 33, 36 and 35. An isolated `asyncvnc==1.3.0` environment was created
under `state/photos-vnc-auth-canary-20261027/`; the live media venv was unchanged.

`ops/photos-vnc-auth-canary.py` made one localhost connection using the native
Apple account authentication. The password was supplied through a private
secret card, read only by a shell process and delivered on SSH stdin. The
private file was removed, and no credential value was logged or retained.
There was no clipboard or keyboard input and no authentication retry.

Authentication succeeded. Five observations while connected still reported
`screen_locked=true`; after disconnect and a second settling check the session
also remained locked with zero viewer connections. Account authentication for
VNC therefore does not by itself unlock this Mac's desktop.

A separate one-shot keyboard experiment was prepared in
`ops/photos-vnc-keyboard-canary.py`. It requires a fresh private secret delivery
and a visual gate: a pre-input screenshot must show the correct user's password
field before any password keystrokes are authorized. It refuses stale approvals,
other viewers, unsupported credentials, or changed session state, and has a
180-second overall deadline.

The user supplied a new private card for this distinct attempt. Authentication
succeeded, and the pre-input screenshot showed the locked `divesensei media`
account, an empty password field, and the `ABC – AZERTY` input source. The
single visually approved submission did not unlock the Mac during the bounded
observation period; it remained locked after disconnect. No retry was made.
The temporary credential file was removed. No clipboard or screenshot after
password input was used. Authentication had accepted the credential, so the
next diagnostic should verify pointer coordinates and keyboard/layout delivery
using harmless text in an unlocked test field before any further login attempt.
Do not conclude either successful unlock or a definitively invalid credential
from this test. User assistance to unlock for that harmless diagnostic was requested.

## Keyboard-verified single unlock attempt (2026-10-27)

The harmless typing fixture round-tripped exactly, including uppercase,
punctuation and accents, with literal VNC key delivery on ABC–AZERTY.
Closing the native Screen Sharing viewer while keeping the test VNC client
connected initially left the session unlocked. The session was then explicitly
locked for the separately authorized single unlock attempt. A pre-input frame
showed the correct account and focused empty password field. One submission
using the verified typing mode left the session locked after eight seconds.
No retry or post-input screenshot was made; the test client was instructed to
stop. No production setting or Photos asset was changed during this attempt.
Unattended unlock and locked-session cleanup remain unproven.

## Paced unlock and full synthetic deletion success (2026-10-27)

A new private credential card authorized one paced attempt: focus the verified
empty password field, wait 0.5 seconds, drain after each key with a 120 ms gap,
then wait one second before Return. This unlocked the session at 19:02:32 UTC;
it relocked after VNC disconnected. This supports a timing/focus explanation
for earlier failures, without establishing which delay was necessary.

A second separately authorized attempt reproduced the unlock at 19:03:29 UTC
and held the authenticated VNC connection open. With no native operator viewer,
the experiment created a fresh synthetic blue video, verified a zero-dialog
baseline, requested deletion of that single recorded UUID, and used the existing
PID/body/button guarded confirmation. PhotoKit completed successfully and the
manifest recorded removed=true. An independent osxphotos catalog read returned
zero visible assets for that UUID. Both temporary Aqua jobs were unloaded,
the UI task reset to read-only, and VNC disconnected; session locked with zero
viewers at 19:04:45 UTC. The initial AppleScript load-script wrapper
failed before confirmation; using run-script with parameters then succeeded.
No password screenshots or persistent credentials were used.

This validates the real locked-session-to-synthetic-deletion chain for this
experiment. It is not integrated into production: secure credential retrieval,
session ownership, bounded connection lifetime and production confirmation
binding still need a deliberate design. Existing production cleanup stays off.

## If Photos access later needs approval

Log into the Mac as `divesensei`. In System Settings > Privacy & Security >
Photos, allow full access for the requesting runtime (Python / DiveSensei
Python Runtime). A denied authorization must be changed in Settings; this
probe only requests authorization when its state is not yet determined.
Keep the existing runtime identity; do not reset TCC, re-sign the installed
app, or change privacy databases to force a grant.

No Automation or Accessibility grant is needed for this PhotoKit probe.
Full Disk Access is a separate concern for the existing catalog reader;
it is not a replacement for PhotoKit read/write authorization.

## Safety contract

Validation after implementation: 460 portable agent tests passed (five native
or optional cases skipped), 53 targeted backend tests passed (cleanup API,
commit API, automatic packages), and 53 CI self-tests passed. Portable Mac
tests injected the same read-refusing osxphotos boundary used on Linux; they
did not open the real library. Release-note validation and diff whitespace
checks passed. The real Mac checks above cover native deletion, not a full
production upload/cleanup rollout.

Release notes: none yet — the Mac worker is not deployed; per
`docs/RELEASE_NOTES.md`, announce the feature in a server release only after
the dependent Mac upgrade is confirmed.

The implementation and rollout must preserve these rules:

- Limit candidates to explicitly ingested Photos video assets assigned to a
  resolved diver other than the configured keeper. Never infer identity from
  an unmatched name or an absent person tag.
- Require durable, checksum-verified uploaded bytes of the edited clip and
  confirmed server metadata/ownership commit. A proxy or local cache is not
  sufficient. Persist enough metadata outside Photos to recover the clip.
- Recheck the asset identity, edit fingerprint, and caption immediately before
  cleanup; skip anything changed since ingestion or shared with a kept clip.
- Produce a dry-run inventory first. Validate actual PhotoKit deletion and
  any system confirmation using an explicitly approved disposable asset,
  through the exact eventual cleanup runtime. Do not test on a friend's clip.
- Use the supported Photos API, never edit Photos.sqlite or remove library
  files. Log completed deletions and retry safely. Leave Recently Deleted alone.

With iCloud Photos, deleting an asset on the Mac also deletes it from the
other devices using the same library. Recently Deleted normally retains it
for 30 days; it must not be treated as the durable backup.

Apple references:

- [PhotoKit authorization](https://developer.apple.com/documentation/photos/phphotolibrary/requestauthorization(for:handler:))
- [Photos usage description](https://developer.apple.com/documentation/bundleresources/information-property-list/nsphotolibraryusagedescription)
- [Asset deletion](https://developer.apple.com/documentation/photos/phassetchangerequest/deleteassets(_:))
- [iCloud deletion behavior](https://support.apple.com/en-ie/104967)
