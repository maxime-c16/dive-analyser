# Mac Media Node Operations

## Photos Rehearsal

Log in locally as `divesensei`:

1. Open Photos and confirm the intended library is the System Photo Library.
2. Confirm iCloud Photos and **Optimize Mac Storage** are enabled. Never select
   Download Originals to this Mac.
3. In System Settings > Privacy & Security, grant Photos and Full Disk Access
   to `/Users/Shared/services/data/diveanalyzer/venv/bin/python` and, if shown,
   its underlying Python interpreter.
4. Run a read-only `osxphotos query --uuid <known-local-uuid> --json` in Terminal.
5. Export exactly one known asset and accept all privacy prompts.
6. Restart, log back in, repeat the query/export, and restart the LaunchAgent.
7. Require `/api/v1/media/agents` to report `photos_access_status: ok` before leasing.

## Service

```bash
launchctl print gui/$(id -u)/com.diveanalyzer.agent
launchctl kickstart -k gui/$(id -u)/com.diveanalyzer.agent
tail -f /Users/Shared/services/logs/diveanalyzer/application.log
```

Installed paths:

- Code: `/Users/Shared/services/data/diveanalyzer/code`
- Venv: `/Users/Shared/services/data/diveanalyzer/venv`
- Config: `/Users/Shared/services/data/diveanalyzer/state/config.yaml`
- Logs: `/Users/Shared/services/logs/diveanalyzer`

## Cutover

1. Verify backend health and zero active/duplicate jobs.
2. Keep new media/sync disabled and new leasing denied.
3. Complete Photos and internal-volume/quota gates.
4. Disable old-agent leasing and verify it has no lease.
5. Enable `mac-media-01` leasing, then media mode with `max_jobs=1`.
6. Run one known poster, then proxy; validate ownership/finalize/playback.
7. Only then enable metadata sync and new-captioned ingestion.

## Storage Operations

Use `/media/recall` to inspect internal free space, quota use, and a bounded
dry-run plan. Page load creates no jobs. Historical plans are limited to six
items. Unknown source size is budgeted as 500 MB with a 2.5x peak multiplier.
Do not proceed if projected free space is below 30 GiB.

Cleanup must first run as a dry run. A destructive pass is capped at 20 files
or 5 GiB and may only remove expired, finalized sources beneath the validated
root. Never manually use recursive deletion against the media-node root.

## Backup

Use one-way `rsync` to Debian without `--delete`. Include redacted config,
LaunchAgent plist, dependency files, manifests, checksums, registry export,
documentation, and permanent sources when capacity permits. Never copy the
optimized Photos library.

## FileVault

FileVault remains off pending an explicit reboot/unlock policy. On this Intel
Mac, enabling it means an unattended remote reboot can stop at preboot login;
SSH, VNC, LaunchAgent, and media processing remain unavailable until local disk
unlock. External recalled sources should ultimately use encrypted APFS if the
physical-risk policy requires it.
