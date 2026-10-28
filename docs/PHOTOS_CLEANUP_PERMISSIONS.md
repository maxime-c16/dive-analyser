# Post-ingest Photos cleanup

Opt-in cleanup keeps the primary diver's clips in Apple Photos and removes only
newly ingested clips unambiguously assigned to another active diver. It uses
PhotoKit; never Photos.sqlite writes or direct file removal. iCloud Photos
propagates deletions to other devices; Recently Deleted is left untouched.

## Ingest and deletion contract

The ordinary ingestion path remains unchanged when cleanup is `off` (default).
When enabled, a fresh export binds the Photos modification version, caption,
edit fingerprint and exported SHA-256 to the upload. Adjusted videos must export
the edited rendition; an original, stale vault file or unreadable recipe cannot
authorize deletion. If the extra export fails, ingestion continues without cleanup.

The queue only receives new, continuous production ingests after full remote
byte verification and a confirmed server commit. Historical journals and library scans are never used to discover deletion
candidates. The authenticated read-only server endpoint rechecks:

- the agent's local Photos UUID mapping;
- an explicit active primary keeper and either one other active diver or a
  complete synchro pair of two other active divers;
- unambiguous person/alias, caption and latest media/caption revisions;
- the committed ledger and verified production B2 object, SHA, size and location.

Unknown, own, lineup and ambiguous clips stay in Photos. Synchros stay too unless
both effective participants are identified active other divers, no conflict exists,
and a new worker pinned the pair revision at fresh-ingest enqueue time.
Any later pair change invalidates that request. Old workers keep every synchro.
Historical review never creates cleanup candidates. See [participants](SYNC_PARTICIPANTS.md). Edits or
metadata changes invalidate old receipts. PhotoKit refetches and compares each
version inside its change block. Completion is recorded only after the asset is
absent. A lost response converges to `already_absent` on the next queue check.

## Modes

```yaml
dual_write:
  enabled: true
  continuous_new_ingest: true
  # Preserve the existing ingest/B2 settings.
  photos_cleanup_mode: dry_run   # off | dry_run | delete
  photos_cleanup_keeper_diver_id: 1  # verify the actual primary diver id first
  photos_cleanup_automated: false
```

`dry_run` writes `would_remove` reports under
`<object_store.state_dir>/photos_cleanup/pending/`. `delete` without automation
requests a native Photos confirmation for at most five assets per five-minute
pass. Failure leaves the item pending with a controlled reason and cooldown.

With `photos_cleanup_automated: true` and `delete`, each pass handles **one asset**
so the helper can recognize the exact singular confirmation tested on this Mac.
Native Apple authentication is mandatory; no-auth/DES fallback is refused.
No other Screen Sharing viewer may be connected, and the session must be locked.
An operator using the Mac causes deferral rather than automation of their desktop.
The worker reads the password from the user Keychain, connects only to local
127.0.0.1:5900 with native Apple account authentication, recognizes the console
user's name and empty password field using Vision, and types with bounded delays.
No screenshot is saved, and none is taken after password input. No clipboard,
password argument, environment variable or configuration value is used.

One attempted authentication/unlock latches failures: after a crash, refused
credential or failed unlock, inspect the Mac and reset the latch explicitly.
There are no automatic password retries. The server and local metadata are
revalidated **after unlock**, before a fresh PhotoKit helper is started.

The separate UI app requires a zero-dialog baseline, a fresh per-request nonce,
the live native helper PID, an armed single-asset marker younger than 20 seconds,
and the exact tested dialog structure/body/buttons. The native helper accepts
only one valid UUID/version in automated mode. Unexpected dialogs or language
changes cause refusal. The current confirmation recognizer supports the tested
English iCloud Photos dialog; it does not guess translations.

On failure, cancellation targets only that same guarded request while the
connection is held. The helper is terminated if still alive, files are disarmed,
and the session is locked before disconnect. Ingestion/sync never wait on the
UI: the cleanup worker is separate and its native request/session are bounded.

**Platform limit:** UserNotificationCenter exposes no requesting PID or asset UUID
in this dialog. The nonce/PID prove our isolated request is alive; baseline plus
exact singular text narrow the dialog match, but cannot provide a macOS-level
cryptographic association to its requester. Automation is therefore an explicit
operator opt-in on this dedicated media Mac, not a general desktop clicker.

## Installation and first activation

Deploy the backend and Mac code with `ci/ship.sh` (dry-run first). No SQL migration
is needed. Keep cleanup `off` throughout setup. Deployment does not install the
optional UI permissions or silently enable deletion.

In Terminal **inside the media Mac's graphical session**, as its regular user:

```bash
BASE=/Users/Shared/services/data/diveanalyzer
# Use the real object_store.state_dir from config.yaml for STATE.
STATE=/path/from/object_store.state_dir
"$BASE/venv/bin/pip" install -r "$BASE/code/requirements-photos-automation.txt"
"$BASE/venv/bin/python" "$BASE/code/setup-photos-cleanup.py" install --state-dir "$STATE"
"$BASE/venv/bin/python" "$BASE/code/setup-photos-cleanup.py" store-password --state-dir "$STATE"
```

The password prompt stores the secret using Security.framework in the logged-in
user's Keychain (`com.diveanalyzer.photos-cleanup`, current account). Ordinary SSH
has a different security context and can return interaction-not-allowed; do not
work around it by saving a password file or weakening Keychain/security settings.
The deployed agent is an Aqua LaunchAgent and reads from that graphical context.
The Mac must already have an open login session after boot; FileVault/pre-login
unlock is outside this feature. Screen Sharing must already be enabled as on the
validated media Mac; no firewall/authentication settings are changed.

The helper lives at `$STATE/photos_cleanup/automation/DiveSensei Photos Cleanup.app`.
Grant that app System Events Automation and Accessibility in System Settings.
PhotoKit read/write permission belongs to the existing signed Python runtime.
Updates replace the external confirmation script without rebuilding the stable
launcher. If the app is recreated or moved, macOS may require reauthorization.

Start with `dry_run`, inspect the proposed UUIDs/keeper against actual ingestions,
then set `delete` and (if desired) `photos_cleanup_automated: true`. Restart the
agent through the documented deployment/configuration procedure. Keep the first
live lot small. This PR does not change the production configuration.

```bash
"$BASE/venv/bin/python" "$BASE/code/setup-photos-cleanup.py" status --state-dir "$STATE"
# Only after inspecting the account/session and resolving the failure:
"$BASE/venv/bin/python" "$BASE/code/setup-photos-cleanup.py" reset-unlock --state-dir "$STATE"
```

Private receipts: `$STATE/photos_cleanup/{pending,completed}/`. Pending reasons
contain no captions, URLs or credentials. The UI protocol directory is private
(0700), and request/armed files are removed after each session. A timed-out UI app is
terminated only when its nonce and process path match, preventing late approvals. To stop: set mode
`off` and automation `false`; no future request starts. An already submitted native
request may still complete, so inspect the current session before changing access.
The Keychain entry remains available for a later activation; remove it explicitly
through Keychain Access if retiring the feature.

## Validation

On macOS, set `DIVE_AGENT_PORTABLE_TESTS=1` when running the portable suite to
force the same read-refusing Photos boundary used in Linux CI.

Portable tests cover ingest proof mismatches, keeper/person ambiguity, changed
metadata/versions, server failures, dry-run/idempotence, bounded batches, fresh
edited exports, native no-op results, OCR account/field binding, password latch,
other viewers, and stale UI responses. Backend tests exercise machine auth and
the read-only eligibility contract.

`ops/photos-cleanup-canary.py` creates/removes only a synthetic video recorded in
a fresh manifest. `ops/photos-cleanup-integration.py` drives the **real queue,
Keychain, OCR unlock, native helper, confirmation and relock** for that manifest
using isolated runtime/state directories and an Aqua job. Its server response and
B2 receipts are explicitly synthetic: it neither uploads nor mutates the live
backend. Backend proof checks are validated independently with database tests.
No personal asset is used for native tests, and Recently Deleted is never emptied.

Real native validation on mac-media-01 (2026-10-27), with the integrated queue
and dedicated UI app:

- Two independent synthetic clips: automatic Keychain → OCR unlock → server
  recheck → PhotoKit confirmation → verified absence → relock succeeded.
- Between those successes, a refusal injected after unlock kept the second
  fixture intact, deferred the queue and restored the lock; retry then succeeded.
- Independent osxphotos catalog verification found neither fixture afterward.
- Both tests started locked with zero viewers. Temporary Aqua jobs were unloaded
  afterward, no armed request remained, and no personal asset was targeted.

Final portable validation: 477 agent tests passed (five optional/native skips),
53 targeted backend tests passed, and 53 CI self-tests passed. The complete local
backend suite had 1,797 passes, 84 skips and three FFmpeg conversion failures;
those exact three failures also reproduce on unchanged `origin/master` on this
Mac. The Linux CI gate remains authoritative. The macOS shell gate wrapper needs
Linux utilities (`flock`, `timeout`), so its Python checks were run directly here.

Historical permission and keyboard experiments are in
[PHOTOS_CLEANUP_EXPERIMENTS.md](PHOTOS_CLEANUP_EXPERIMENTS.md).

Release notes: none — activation depends on a separately confirmed Mac rollout.
Per [RELEASE_NOTES.md](RELEASE_NOTES.md), announce in a server PR after that upgrade.
