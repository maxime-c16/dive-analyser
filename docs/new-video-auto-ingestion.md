# New Video Auto Ingestion

Automatic media preparation applies only to newly detected, recognized
DiveSensei-captioned movies. It remains disabled until catalog Stage 2 has
completed safely and one new or controlled simulated asset has passed:

```text
detection -> catalog upsert -> P2 priority -> one-asset recall
-> poster -> proxy_360p -> Debian validation -> source cleanup
```

New videos preempt historical backlog after the current item. They do not
interrupt an active Photos export. Metadata polling remains 5-15 minutes and
media concurrency remains one.

Do not set `NEW_VIDEO_AUTO_MEDIA_ENABLED=true` merely because cataloging works.
The full ingestion path and storage cleanup must be verified first.
