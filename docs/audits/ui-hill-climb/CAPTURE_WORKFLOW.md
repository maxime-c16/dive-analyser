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

Continuation: full frontend suite passed with Node 26 experimental webstorage
disabled (`NODE_OPTIONS=--no-experimental-webstorage`): 118 files, 969 tests.
The default Node run had 81 failures and is not reported green. Local pre-push
failed because nproc/timeout/Docker prerequisites are absent; published using the
repository's documented DIVE_CI_SKIP option for authoritative GitHub checks.
Round 7 is an explicitly provisional screenshot diagnostic, not an acceptance
round. Sol observed only Library grid (5.5/10); matrix retained in round-07.
The script now rejects unsuccessful network quiet waiting and checkpoints its
manifest after every capture so slow pages do not hide completed evidence.

Fresh f1afe9bb Library grid captured at five sizes in the focused run: header
collision corrected, phone scope visible. Raw bundle:
`.ui-council/f1afe9bb80c1-a251437a502d-1793889489032/`.
Phone/landscape player actions wrap correctly. Player images at desktop/tablet/
landscape still contain `.clip-loading`: rejected as settled video evidence;
added that loader to both waiting and metrics. No player acceptance inferred.
The header comparison in round-07/images is a top-only crop with separate
numbered annotations. Originals stay in the private ignored bundle; no media or
DM text appears in the crop. This compares the pre-fix product and f1afe9bb at
390×844. Historical full run completed in 561s (20 failed/unsettled); focused
Library grid/player run completed in about 30s. Incremental manifests and
no automatic retries of unsettled frames avoid the original long feedback loop.
