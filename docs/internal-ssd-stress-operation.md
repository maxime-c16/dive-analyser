# Internal SSD Stress Operation

The Photos library is managed only by Photos/macOS. DiveSensei must never edit
its package, database, originals, or caches.

Stress-run gates:

| Stage | Minimum free space |
|---|---:|
| Catalog metadata | 22 GiB |
| Start new historical recall | 12 GiB |
| Start automatic/new-video recall | 11 GiB |
| Continue active item | 11 GiB |
| Warning | 15 GiB |
| Stop before stage | 11 GiB |
| Absolute worker stop | 10 GiB |

Every planned recall must also remain above 10 GiB after its conservative peak
estimate. Reserve 10 GiB for Photos growth. Active source/export/transcode workspace is
limited to 3 GiB. Successful bulk sources are temporary and should be removed
after durable poster/proxy verification; failed diagnostics are retained for six
hours during a controlled stress run.

Record free space, Photos-library size, workspace bytes, and cache growth at
start, every 25 completed items, every pause, and completion.
