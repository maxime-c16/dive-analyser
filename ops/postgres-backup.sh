#!/usr/bin/env bash
# postgres-backup.sh — DIVE_ANALYZER Postgres backup policy executor (P9-C).
#
# Policy (docs/architecture/BACKUP_AND_RETENTION_V1.md):
#   frequency   : daily (cron), plus ad-hoc manual runs
#   format      : pg_dump custom format (-Fc, internally compressed)
#   encryption  : AES-256-CBC + PBKDF2 (openssl), key file 0600, never in Git
#   destination : local ~/backups/postgres/ (server)
#                + optional off-host rsync push (see BACKUP_OFFHOST_*)
#   retention   : keep the newest BACKUP_KEEP_DAILY daily + BACKUP_KEEP_WEEKLY
#                 weekly backups; older encrypted files are pruned
#   restore test: ops/postgres-restore-test.sh (isolated container, non-destructive)
#
# Security: no passwords on command lines (container-local peer auth), key
# file readable only by the owner, backup.log must never contain secrets.
# The script NEVER touches the production database except through a
# consistent single pg_dump read connection.

set -eu

CONFIG_FILE="${1:-/home/mcauchy/dive-analyser/ops/postgres-backup.env}"
if [ -f "$CONFIG_FILE" ]; then
  # shellcheck disable=SC1090
  . "$CONFIG_FILE"
fi

POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-dive-analyser-postgres-1}"
POSTGRES_USER="${POSTGRES_USER:-diving}"
POSTGRES_DB="${POSTGRES_DB:-diving_analyzer_db}"
BACKUP_DIR="${BACKUP_DIR:-/home/mcauchy/backups/postgres}"
KEY_FILE="${KEY_FILE:-/home/mcauchy/backups/postgres/.backup_key}"
KEEP_DAILY="${BACKUP_KEEP_DAILY:-14}"
KEEP_WEEKLY="${BACKUP_KEEP_WEEKLY:-8}"
OFFHOST_DEST="${BACKUP_OFFHOST_DEST:-}"
OFFHOST_KEY="${BACKUP_OFFHOST_KEY:-/home/mcauchy/.ssh/id_ed25519_backup_push}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DOW="$(date -u +%a)"
mkdir -p "$BACKUP_DIR"
if [ ! -f "$KEY_FILE" ]; then
  echo "[pg-backup] FATAL: key file missing: $KEY_FILE (see docs/architecture/BACKUP_AND_RETENTION_V1.md)" >&2
  exit 2
fi
chmod 600 "$KEY_FILE"

RAW="$BACKUP_DIR/${STAMP}.dump"
ENC="$BACKUP_DIR/${STAMP}.dump.enc"
SUMS="$BACKUP_DIR/${STAMP}.sha256"

T_START=$(date +%s)
docker exec "$POSTGRES_CONTAINER" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc >"$RAW"
T_DUMP=$(date +%s)

if [ ! -s "$RAW" ]; then
  echo "[pg-backup] FATAL: empty dump; aborting (nothing written to encrypted storage)" >&2
  rm -f "$RAW"
  exit 1
fi

openssl enc -aes-256-cbc -pbkdf2 -salt -in "$RAW" -out "$ENC" -pass file:"$KEY_FILE"
rm -f "$RAW"
T_ENC=$(date +%s)

# Readability verification: decrypt into a temp file and ask pg_restore to
# parse the archive TOC (fail-closed: a broken backup must fail the run).
TMP_VERIFY="$(mktemp)"
trap 'rm -f "$TMP_VERIFY"' EXIT
if ! openssl enc -d -aes-256-cbc -pbkdf2 -in "$ENC" -out "$TMP_VERIFY" -pass file:"$KEY_FILE"; then
  echo "[pg-backup] FATAL: backup failed to decrypt" >&2
  rm -f "$ENC"
  exit 1
fi
if ! cat "$TMP_VERIFY" | docker exec -i "$POSTGRES_CONTAINER" pg_restore --list >/dev/null 2>&1; then
  echo "[pg-backup] FATAL: backup archive unreadable by pg_restore" >&2
  rm -f "$ENC"
  exit 1
fi
T_VERIFY=$(date +%s)

# Integrity manifest (encrypted file + sha256; the manifest is NOT secret).
sha256sum "$ENC" >"$ENC.sha256"
chmod 600 "$ENC" "$ENC.sha256"

# Retention: daily (all) + weekly (Sunday) buckets.
ls -1 "$BACKUP_DIR" | grep -E '^[0-9]{8}T[0-9]{6}Z\.dump\.enc$' | sort >/dev/null 2>&1 || true
python3 - "$BACKUP_DIR" "$KEEP_DAILY" "$KEEP_WEEKLY" <<'PYEOF'
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

backup_dir = Path(sys.argv[1])
keep_daily = int(sys.argv[2])
keep_weekly = int(sys.argv[3])
pat = re.compile(r"^(\d{8}T\d{6}Z)\.dump\.enc$")
entries = []
for path in backup_dir.glob("*.dump.enc"):
    match = pat.match(path.name)
    if not match:
        continue
    dt = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    entries.append((dt, path))
entries.sort(reverse=True)
daily = entries[:keep_daily]
weekly = [e for e in entries if e[0].weekday() == 6][:keep_weekly]
keep = {e[1].name for e in daily} | {e[1].name for e in weekly}
removed = 0
for dt, path in entries:
    if path.name not in keep:
        path.unlink(missing_ok=True)
        checksum = path.with_name(path.name + ".sha256")
        checksum.unlink(missing_ok=True)
        removed += 1
print(f"[pg-backup] retention: kept {len(keep)} pruned {removed}")
PYEOF

# Optional off-host push (encrypted bytes only; the key never leaves).
if [ -n "$OFFHOST_DEST" ]; then
  if rsync -a --no-times --no-perms \
      -e "ssh -i $OFFHOST_KEY -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new" \
      "$ENC" "$ENC.sha256" "$OFFHOST_DEST/"; then
    echo "[pg-backup] off-host push OK"
  else
    echo "[pg-backup] WARNING: off-host push failed (local copy remains authoritative)" >&2
  fi
fi

T_END=$(date +%s)
BYTES=$(stat -c%s "$ENC")
echo "[pg-backup] OK stamp=$STAMP bytes=$BYTES dump=$((T_DUMP-T_START))s encrypt=$((T_ENC-T_DUMP))s verify=$((T_VERIFY-T_ENC))s total=$((T_END-T_START))s"
