# Fast council evidence

From `frontend/`, run `node scripts/ui-council-capture.mjs capture --serve --pages 1`.
This builds this worktree and proxies the real API. The saved owner session must
already exist outside Git; use the supported `login` command when needed.
The script rejects any identity other than maxime and blocks API writes.

Each execution creates a separate ignored `.ui-council/<head>-<source hash>-<timestamp>/`
folder. Read `MANIFEST.md` first, then `sheets/<scenario>.png` to compare five
sizes, then original `shots/<scenario>/<size>.png` for close inspection.
All retry attempts are retained in `manifest.json`; failed or unsettled captures
are not approval evidence. The source hash includes tracked and untracked frontend
files. Do not change frontend source while a capture runs.

Current automated scope: 21 scenarios × five sizes. Live Judge Room phases and
judging submissions remain explicit coverage gaps. Static screenshots cannot prove
interactions or independent reviewer authentication. Use existing phase evidence
only when its candidate provenance matches, otherwise recapture those flows.
No full 14×5 passing claim follows from a successful screenshot command.

Bundles contain private conversation/media content and must stay outside Git.
Never upload raw bundles. PR images require the separate privacy-reviewed gallery.

2026-11-05 continuation: browser default profile redirected `/account` to `/login`;
saved script session independently verified maxime. TypeScript and 118 targeted
product tests passed. Previous 105-image bundle took 162 seconds but inspection
found a PageLoading frame falsely classified settled; `.eval-warmup` is now
included in both waiting and final loader checks. Previous bundle is historical,
not final acceptance evidence.
