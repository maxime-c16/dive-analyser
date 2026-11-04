# UI hill climb evidence

Candidate origin: http://localhost:4317. Browser profile: default. Worktree branch: t3/hill-climb-ui. No merge or deployment.

## Invariants

Ownership, filters, paging, scores and write actions retain their existing contracts. Score-card spiral artwork is intentional and stays. UI changes do not alter authentication. The final Vite dev proxy uses changeOrigin:false and preserves the browser Host. Optional HTTPS uses explicit upstream SNI. Public Funnel TLS failed independently in curl and Node, so SNI was not proven the sole cause. The fixed localhost4317 runtime now routes through an SSH tunnel to the existing server front door. No remote changes or authentication weakening. Signed /media paths also proxy there; thumbnails and byte-range video were verified.

## Design direction

Keep the existing dark diving-video workspace: background #0d1113, panel #15191c, raised panel #191f23, text #edf2f4, muted #98a2aa, accent #54beab. Retain the existing sans typeface, 30/36px page headings, 17px section headings and 14/16px content. Align content left. Footage and people lead; filters and statistics follow. Controls use restrained outlines and clear selected states. Remove passive podium/arrival decoration where it competes with a task. Keep score-card domain artwork.

## Preflight 00

Initial production /account showed Signed in as maxime; auth/me 200. Initial local origin had no session (401). User completed persistent login after parent fixed Vite's Host forwarding; own local /account subsequently showed Signed in as maxime and auth/me 200 display_name=maxime. Muse's independent local preflight also passed. Other authenticated preflights are pending delivery; no UI council scores have been assigned.

Initial 25 production screenshots were retained outside git. They are captured/unreviewed, with no settled guarantee and no claim about deployed source SHA. A mistaken /judge-room route was captured; the real route is /room. These invalid captures cannot be used as passing evidence. A subsequent five-size /room pass waited for .gm-home. Additional baseline captures use local source ef05e126 plus the required dev-only proxy change, temporarily restoring UI source then restoring the saved implementation. Screens that failed to load are unverified, including missing child flows.

## First pass (uncommitted)

- Library: two mobile columns, three small-screen columns, four large-screen columns, six wide-screen columns; compact upload action in the title row.
- Community: directory before rankings; rankings use ordered rows while preserving all top-ten entries and the current viewer outside the top ten.
- Messages: conversation height follows measured position and navigation space; remove 480px minimum in short viewports; inbox uses a smaller share of tablet width.
- Evaluations: align desktop/mobile heading scale.
- Judge Room: scrolling viewport, visible return during playback and other phases, visible pending room creation state.

## Checks

Node 26.5.0 caused two existing Library tests to fail because localStorage was undefined. Rerun under installed Node 20 (matching CI): 40/40 Library+Community tests passed. After ranking changes, Community and Messages: 29/29 passed under Node 20. Initial production build passed; typecheck passed. Checks must run again on the final source.

## Baseline factual corrections

- The score-card spiral is intentional decoration, not duplicated digits.
- Calendar ERR_NETWORK_CHANGED recovered through Retry.
- Detailed analysis 201C returned 500, then Retry returned 200; cause remains unknown.

## Remaining gate

Complete settled captures/interactions for every main and child journey at all five sizes, fix weak layouts, run relevant checks, commit a candidate, then obtain three independent 70-cell council matrices against that same commit. Missing coverage remains null/unverified. Publish sanitized annotated before/after images in the PR, with original captures retained, immutable release note, and per-round findings. No threshold claimed yet.

## Candidate run 01

Three independent authenticated preflights passed in separate default-profile tabs: Codex Sol low, Muse Contributor xhigh, GLM Flash max. Each proved Signed in as maxime and auth/me200. These are not UI reviews.

Implementation: compact Library upload and larger previews; code detail disclosures; session medians as default for dense histories with explicit Attempts preserved; directory before ordered rankings; profile statistics disclosure; measured conversation height; plain community means; quieter Calendar detail sections; Judge Room Back, pending creation, score context, short-height scoring layout and ordered results. Short-height main journey styles exclude operational workspaces. Score-card spiral remains intentional artwork.

Final direct frontend checks: Node20, 115 files/948 tests PASS; tsc+Vite build PASS; release note validation PASS; diff check PASS. Global ci/gate.sh cannot run here because nproc, timeout, Docker and PyYAML are absent. No global gate green claim. Native Room numerical-button automation sometimes timed out; existing DOM button click fallback was used, without state injection or write API calls.

Self assessment and coverage: run-01/self-scorecard.json. Gallery is a draft: original PNGs retained outside Git with hashes, sanitized comparisons under run-01/images. Some old captures are unsettled; they are excluded and cannot prove a score increase. Child comparisons and annotation QA remain required before filing PR. Independent council matrices are pending, so the user exit threshold is not reached.

## Corrected candidate run 02

After STOP, both unfinished GLM records were read and retained as interrupted, with no final scores. User restored local login through normal form. Own fresh default tab/account proved maxime/auth200, WebSocket open, real preview webp200. My dives now has real previews/date/time plus exact clip links. Progressive identity reads never block the score list, use at most four concurrent requests for the existing twenty-row page, timeout after8seconds and abort on page change. No backend/API changes. Imported records can share timestamps; no invented metadata. Short landscape lobby now places panel beside mode/source/Start; actual844x390Startbottom314. All five sizes captured without horizontal overflow. Foreground own auditroom score6 armed Submit and reached results; earlier background failure remains unexplained.

Latest checks:116files951testsPASS, production buildPASS, typecheckPASS, release notePASS, diffcheckPASS. Sanitized actual comparisons: [run02 gallery](run-02/GALLERY.md), with original hashes. Run01 gallery drafts remain uncommitted and must not be represented as final reviewed proof. Independent final councils and remaining child galleries still required; no threshold claim.
