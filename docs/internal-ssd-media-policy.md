# Internal SSD Media Policy

The Mac media node uses a selective working set on its 128 GB internal SSD.
The optimized Photos library is not managed source storage and is never copied
or exported wholesale. Debian remains the durable cache.

## Gates and Quotas

| Control | Limit |
|---|---:|
| Warning | 35 GiB free |
| Historical recall pause | 30 GiB free |
| Automatic recall pause | 24 GiB free |
| Emergency processing stop | 18 GiB free |
| Managed source quota | 20 GiB |
| Maximum approved configurable quota | 25 GiB |
| Automatic source maximum | 1 GiB |
| Hard single-source maximum | 2 GiB |

Both the projected free-space gate and managed quota must pass. Historical
planning assumes 500 MB when size is unknown and reserves 2.5 times the source
size for export duplication, transcode output, and diagnostics.

The expected Data volume UUID is
`68C4DD7B-F527-46DE-8481-5D01F49F21DA`. Cleanup and source imports fail closed
on a UUID mismatch, symlink, path escape, or read-only volume.
