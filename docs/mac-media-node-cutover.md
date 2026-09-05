# Mac Media Node Cutover

## Required Gates

1. Photos heartbeat is `ok` from the LaunchAgent audit session.
2. System Photo Library, iCloud Photos, and Optimize Mac Storage are visually
   confirmed; Download Originals remains off.
3. Internal volume UUID, 20 GiB quota, and all free-space gates pass.
4. One recalled source produces a finalized poster and proxy served by Debian.
5. Cleanup dry-run and bounded destructive rehearsal pass.
6. No active media job or duplicate lease exists.

## Atomic Procedure

1. Disable `mac-media-old` leasing and verify no lease remains.
2. Leave `mac-media-01` processing disabled, then enable only its backend lease.
3. Enable new-agent media mode with `max_jobs=1`.
4. Request one poster and wait for ready.
5. Request its proxy and wait for ready.
6. Verify HEAD 200, Range 206, checksum, H.264/yuv420p, and AAC where present.
7. Leave the new worker active only if heartbeat, storage, cleanup, and lease
   ownership remain healthy. Keep the old worker installed but disabled.

If any gate fails, disable new leasing and media mode before re-enabling the old
worker. Never allow both workers to lease concurrently.
