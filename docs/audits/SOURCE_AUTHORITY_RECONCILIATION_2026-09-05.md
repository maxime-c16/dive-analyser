# SOURCE AUTHORITY RECONCILIATION — 2026-09-05

Scope: repository-side source reconciliation only. **No runtime deployment change was
made.** The running Mac agent, launchd job, server Docker stack, DB and media were not
modified.

## 1. Preflight

- Canonical repo re-verified before any write:
  `mcauchy@192.168.1.57:~/dive-analyser`, branch `uiux-overhaul-pro-app`,
  HEAD `7ae8b0186d21bd040c0af2caf675cd6080e365a3`, single commit (2026-02-03),
  no remotes — matches the prior cartography packet exactly.
- Local Mac copy `~/.perso/diveanalyzer`: confirmed NOT a git repo; contains the two
  previous-agent docs, used as source material after review.
- SSH access established passwordless (key `qwokka` installed on both hosts at the
  operator's request; aliases `diveanalyzer-server` / `diveanalyzer-mac`).

## 2. Server repo identity

- Path `/home/mcauchy/dive-analyser`, branch `uiux-overhaul-pro-app`.
- HEAD `7ae8b0186d21bd040c0af2caf675cd6080e365a3` (2026-02-03 12:27:35 +0100,
  "Restructure: Move app code from diving-analyser/ to dive-analyser/ …"), 1 commit.
- Working tree very dirty (559 status entries): staged doc/app changes, untracked
  `mac-agent/` and `docs/`, modified `.env`, tracked AppleDouble `._*` files, a DB
  dump, `backups/`, `media/`. None of this pre-existing state was committed by this task.
- `mac-agent/` was **untracked** (packet said "tracked" — fresh evidence recorded).

## 3. Mac deployed identity

- Host `mac-server.home` (192.168.1.19, macOS 15.1.1, user `divesensei`).
- Root `/Users/Shared/services/data/diveanalyzer/` with:
  - `code/` — deployed source tree (20 src modules, 6 test files, build/deploy files, docs);
  - `state/config.yaml` — runtime config, 0600 (secrets; key names inventoried, values never read into any artifact);
  - `bin/` — vendored ffmpeg 8.1.2-tessus, ffprobe, uv/uvx;
  - `venv/` — Python 3.12.13; osxphotos 0.76.1; agent installed editable from `code/`.
- launchd `com.diveanalyzer.agent` (PID 16245, up since 5 Aug 2026): wrapper app
  "DiveSensei Python Runtime.app" → `venv/bin/python -m src.main --config
  /Users/Shared/services/data/diveanalyzer/state/config.yaml`,
  WorkingDirectory `code/`, KeepAlive on non-zero exit, logs under
  `/Users/Shared/services/logs/diveanalyzer/`.
- Deployed tree has no `.git`; no `.bak/.old/.orig/tmp` files; one stray duplicate:
  `code/mac-agent/src/photos_reader.py` (byte-identical to `src/photos_reader.py`).

## 4. Old repo-agent inventory (pre-reconciliation `mac-agent/`, untracked)

14 files: `config.example.yaml`, `deploy/…plist`, 10 `src/` modules, 2 test files.
Identical to deployed: `src/extractor.py`, `src/media_uploader.py`,
`config.example.yaml`, `deploy/com.diveanalyzer.agent.mac-media-01.plist`,
`tests/test_metadata.py`.

## 5. Deployed-agent inventory (post-reconciliation `mac-agent/`)

96 files: 20 `src/` modules (`__init__`, config, crash_recovery, error_recovery,
extractor, log_rotation, main, media_catalog, media_exporter, media_jobs,
media_materializer, media_uploader, metadata, network, photos_reader, queue,
source_vault, sync_client, transcoder, types), 6 test files, `conftest.py`,
`config.example.yaml`, `pyproject.toml`, `requirements.txt`, `setup.py`, `README.md`,
`install.sh`, `uninstall.sh`, `upgrade.sh`, root + deploy plists, full `docs/` tree
(ARCHITECTURE, API, media-node ops, `archive/`, `reference/` incl. one PNG).

Deployed source identity: entrypoint `src.main:main` (`-m src.main`); config loaded by
`src/config.py` from YAML; osxphotos 0.76.1; protocol endpoints used:
`/api/v1/videos/sync`, `/api/v1/videos/label`, `/api/v1/media/jobs/lease` (+job ops),
`/api/v1/media/catalog/runs/lease`, `/api/v1/media/agents/heartbeat`,
`/api/v1/media/agents/sources/report`.

## 6. Diff classification

| Class | Items |
|---|---|
| SOURCE | 9 updated modules (`config, main, media_exporter, media_jobs, media_materializer, photos_reader, source_vault, sync_client` + `tests/test_media_safety.py`); 10 new src modules; 5 new test files; conftest; build/deploy files; docs tree |
| CONFIG_TEMPLATE | `config.example.yaml` (already identical); both plists (path templates) |
| RUNTIME_CONFIG | `state/config.yaml` — key names inventoried only (`server.url/api_key`, `agent.*`, `photos.*`, `sync.*`, `media.*` incl. `source_vault.*` quotas, `logging.*`); values never copied |
| SECRET | `docs/archive/DEPLOYMENT_READY.md` contains a hardcoded credential → excluded from Git; `config.example.yaml` and `tests/conftest.py` contain placeholders only |
| GENERATED | `__pycache__`, `.pytest_cache`, `*.egg-info`, `logs/`, `.DS_Store`, `._*` — excluded |
| VENDORED_DEPENDENCY | `bin/ffmpeg`, `bin/ffprobe` (8.1.2-tessus), `uv` — NOT committed; represented by version notes + requirements pinning |
| DATA | Photos library, source vault, sync state, media, DB — never touched |

## 7. Files canonicalized

Deployed `code/` tree → repo `mac-agent/` via rsync (byte-exact), minus the excluded
classes above and minus `docs/archive/DEPLOYMENT_READY.md`. 96 files total.
`rsync --delete` removed nothing that still exists on the Mac side; the previous stale
repo copy's 14 files are all represented (9 updated, 5 byte-identical).

## 8. Files intentionally excluded

- `docs/archive/DEPLOYMENT_READY.md` — embedded credential (see §9).
- All GENERATED/VENDORED/DATA items in §6.
- Stray duplicate `code/mac-agent/…` (documented, not copied).

## 9. Secrets / runtime-state handling

- Candidate files scanned for keys/passwords/tokens/private keys before staging.
- Only real finding: `DEPLOYMENT_READY.md` credential → excluded from commit; runtime
  file untouched on the Mac; key NAME documented, value not reproduced here.
- `state/config.yaml` read only to inventory structure; values redacted at source of analysis.

## 10. Source-parity result

**PASS.** Every application-source/config file needed by the deployed agent
(37 files: src, tests, build, deploy, template config, plists) is byte-identical in
repo `mac-agent/` (md5-verified per file). The 15 stale-test failures are confined to
`tests/test_sync_client.py` (pre-rewrite API); noted as a known issue, NOT reconciled
(no behavior-changing edits allowed in this task).

## 11. Byte-parity exceptions

Intentional non-parity: runtime config (`state/config.yaml`), vendored binaries
(`bin/`), venv, `__pycache__`/caches/logs, `.DS_Store`/`._*`, egg-info, stray duplicate
`code/mac-agent/…`, and `docs/archive/DEPLOYMENT_READY.md` (in Mac only, credential).

## 12. Testing

- `PYTHONDONTWRITEBYTECODE=1 pytest tests -q -p no:cacheprovider` on the Mac against
  the deployed venv: **54 passed, 15 failed** (all in stale `test_sync_client.py`).
  No cache or bytecode written to the deployed tree (verified).
- `python3 -m py_compile mac-agent/src/*.py` on the server repo copy: SYNTAX_OK.

## 13. Resulting Git state

- Branch `uiux-overhaul-pro-app`; one new commit created 2026-09-05 containing only:
  `mac-agent/**` (96 files), `docs/PROJECT_STATE.md`,
  `docs/audits/REPOSITORY_CARTOGRAPHY_2026-09-05.md` (+ addendum),
  `docs/audits/SOURCE_AUTHORITY_RECONCILIATION_2026-09-05.md`.
- Path-limited commit used so the pre-existing staged/uncommitted backend+frontend
  work remains untouched and uncommitted. Exact SHA in `git log` / LOCAL_AGENT_REPORT.
- Commit not deployed anywhere; runtime untouched.

## 14. Remaining risks

- Backend/frontend live code exists only as uncommitted working tree in the canonical
  repo (single-commit HEAD is months stale). Biggest durability gap remaining.
- Repo hygiene: AppleDouble `._` files tracked in HEAD; DB dump + backups inside repo dir.
- Stale `test_sync_client.py`; `DEPLOYMENT_READY.md` credential still on the Mac.
- Security items (stub API-key auth, HTTP, CORS, Adminer/Postgres exposure) unchanged —
  explicitly out of scope.

## 15. Supervisor decisions still required

1. Commit (or otherwise durable-ize) the pre-existing uncommitted backend/frontend work.
2. Approve a hygiene pass: untrack `._*` AppleDouble files, move DB dump/backups out of the repo tree.
3. Approve refreshing/removing stale `tests/test_sync_client.py`.
4. Approve scrubbing the credential from `docs/archive/DEPLOYMENT_READY.md` on the Mac.
5. Whether vendored ffmpeg/ffprobe should get a reproducible download/install script.
6. Security remediation sequencing (auth, TLS, exposure) — separate gate.
