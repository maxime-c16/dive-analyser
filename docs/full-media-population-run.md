# Full Media Population Run

Population is planned from the latest complete catalog revision. Priority is:

```text
P0 explicit need
P1 representative gaps
P2 recent 180-day clips
P3 ordinary eligible backlog
P4 retryable operational failures
```

The dry-run planner creates zero jobs, recalls, and files. It estimates final
Debian cache growth separately from Mac peak usage. Peak usage is one source
with export/transcode overhead, capped at the 3 GiB active-workspace budget.

Execution may start only when Photos health is `ok`, free space is at least 32
GiB, no duplicate job exists, and only `mac-media-01` can lease. Renditions are
poster then `proxy_360p`, from the same retained source. Stage limits are 10,
50, 200, then rolling checkpoints of 100. A stage must never pre-create the
full backlog as media jobs.

Current production policy keeps execution disabled when the planner reports a
storage block. Catalog completion does not imply population permission.
