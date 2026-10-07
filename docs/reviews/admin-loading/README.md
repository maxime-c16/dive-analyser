# Administrator user-list loading

The original mobile Administration page took 12.75 seconds to show users on
production. Both `/admin/users` and `/admin/divers` spent about 12.07 seconds
waiting. It also requested `/operations/status` for the hidden System tab.
That route called synchronous SQLAlchemy and representative-media diagnostics
inside an `async def`, blocking the backend event loop. Blocking only the
System-status request in the browser reduced the unchanged production page's
load to 0.43 seconds (users API: 134 ms).

The fix requests and polls diagnostics only while System is visible. Polling
waits for completion before starting its 15-second delay, and leaving System
aborts its request. The synchronous status endpoint now runs in FastAPI's
worker pool so a System viewer cannot stall other users.

The final recordings measured **11.80 seconds before** and **1.49 seconds
after**, including navigation and authentication.

## Videos

- `before.mp4`: original production frontend and backend.
- `after.mp4`: candidate production frontend bundle, proxied to the same live
  backend; this isolates the frontend fix before deploying the backend fix.
- `before-after.mp4`: both recordings, side by side; the completed after frame
  stays visible while the original page is still loading.

Recordings use a 393 × 852 mobile viewport, real authenticated requests and
real backend timings. Names and emails are replaced with example values in
API responses before rendering. The release hint is suppressed using its
normal browser cooldown. No response delays, fixture users, session tokens or
production media are included in the committed evidence.

Reproduce from the repository root after installing frontend dependencies and
a Playwright Chromium browser:

```sh
ADMIN_STORAGE_STATE=/private/temporary-state.json \
ADMIN_RECORD_LABEL=before node docs/reviews/admin-loading/record.cjs
# For the candidate bundle, build and serve with vite preview using
# PREVIEW_PROXY_TARGET pointing to the backend, then set ADMIN_BASE_URL.
```

The script writes videos under `/tmp/`; convert them to MP4 with ffmpeg.
The temporary authentication state must remain outside the repository and its
verification session must be revoked after checking production.

## Regression coverage

The new frontend tests cover zero diagnostics requests on Users, tab-exit
cancellation, on-demand fetching, and non-overlapping polling. The backend
concurrency test holds a snapshot open and verifies that health still responds.
All four tests fail against the original code and pass against the fix.

No migration, nginx change or Mac-agent deployment is required. Deploy both
frontend and backend with `ci/ship.sh server` after merging.
