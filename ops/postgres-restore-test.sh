#!/usr/bin/env bash
# postgres-restore-test.sh — NON-DESTRUCTIVE restore validation (P9-C §9).
#
# Proves, for the newest local encrypted backup:
#   - the backup decrypts and pg_restore can read it
#   - the full schema restores into an ISOLATED throwaway Postgres 16
#     container (never the production DB)
#   - row-count reconciliation for the critical table families matches the
#     live production database:
#       user/auth tables (app_users, user_credentials, user_sessions,
#         user_diver_access, login_attempts, media_playback_grants)
#       dives / domain data
#       media backbone tables (media_blobs, media_revisions,
#         caption_revisions, media_blob_locations, ingest_object_state)
#       security audit log
#   - the media ownership chain is preserved: every media_revisions row
#     joins to a dive and an OWNER user_diver_access row
#
# It never writes to the production database and never restores over it.
# Requires docker; uses a random port bound to loopback only.

set -eu

CONFIG_FILE="${1:-/home/mcauchy/dive-analyser/ops/postgres-backup.env}"
if [ -f "$CONFIG_FILE" ]; then
  # shellcheck disable=SC1090
  . "$CONFIG_FILE"
fi

BACKUP_DIR="${BACKUP_DIR:-/home/mcauchy/backups/postgres}"
KEY_FILE="${KEY_FILE:-/home/mcauchy/backups/postgres/.backup_key}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-dive-analyser-postgres-1}"
POSTGRES_USER="${POSTGRES_USER:-diving}"
POSTGRES_DB="${POSTGRES_DB:-diving_analyzer_db}"
RESTORE_CONTAINER="${RESTORE_CONTAINER:-diveanalyzer-restore-test}"
RESTORE_PORT="${RESTORE_PORT:-55432}"
RESTORE_DB="${RESTORE_DB:-restore_test}"

# 1. newest encrypted backup
LATEST="$(ls -1 "$BACKUP_DIR" 2>/dev/null | grep -E '^[0-9]{8}T[0-9]{6}Z\.dump\.enc$' | sort | tail -1 || true)"
if [ -z "$LATEST" ]; then
  echo "[restore-test] FATAL: no encrypted backup found in $BACKUP_DIR (run ops/postgres-backup.sh first)" >&2
  exit 2
fi
ENC="$BACKUP_DIR/$LATEST"
echo "[restore-test] backup: $LATEST"

# 2. decrypt + archive sanity
T0=$(date +%s)
DECRYPTED="$(mktemp)"
trap 'rm -f "$DECRYPTED"; docker rm -f "$RESTORE_CONTAINER" >/dev/null 2>&1 || true' EXIT
openssl enc -d -aes-256-cbc -pbkdf2 -in "$ENC" -out "$DECRYPTED" -pass file:"$KEY_FILE"
T_DECRYPT=$(date +%s)
echo "[restore-test] decrypt: $((T_DECRYPT-T0))s"

# 3. isolated container
docker rm -f "$RESTORE_CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$RESTORE_CONTAINER" \
  -e "POSTGRES_USER=$POSTGRES_USER" -e "POSTGRES_DB=$POSTGRES_DB" \
  -e "POSTGRES_HOST_AUTH_METHOD=trust" \
  -p "127.0.0.1:$RESTORE_PORT:5432" postgres:16 >/dev/null
T_CONT=$(date +%s)
until docker exec "$RESTORE_CONTAINER" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do
  sleep 0.5
done
echo "[restore-test] isolated container ready: $(( $(date +%s)-T_CONT ))s"

# 4. restore
T1=$(date +%s)
cat "$DECRYPTED" | docker exec -i "$RESTORE_CONTAINER" pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --role="$POSTGRES_USER" >/dev/null 2>&1 || {
  echo "[restore-test] FATAL: pg_restore failed" >&2
  exit 1
}
T_RESTORE=$(date +%s)
echo "[restore-test] restore: $((T_RESTORE-T1))s"

# 5. row-count reconciliation against production
TABLES="app_users user_credentials user_sessions user_diver_access login_attempts media_playback_grants dives divers media_blobs media_revisions caption_revisions media_blob_locations ingest_object_state security_audit_log"

FAIL=0
declare -A SRC REST
for t in $TABLES; do
  SRC[$t]="$(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM $t")"
  REST[$t]="$(docker exec "$RESTORE_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM $t" || echo ERR)"
  if [ "${SRC[$t]}" != "${REST[$t]}" ]; then
    echo "[restore-test] MISMATCH $t: source=${SRC[$t]} restored=${REST[$t]}"
    FAIL=1
  else
    echo "[restore-test] OK $t = ${SRC[$t]}"
  fi
done

# 6. critical chain: media ownership preserved in the restored DB
CHAIN="$(docker exec "$RESTORE_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "
  SELECT count(*) FROM media_revisions r
  JOIN dives d ON d.video_uuid = r.video_uuid
  JOIN user_diver_access a ON a.diver_id = d.diver_id AND a.access_kind = 'OWNER'
  JOIN app_users u ON u.id = a.user_id AND u.is_active;")"
echo "[restore-test] ownership chain rows restored: $CHAIN"
CHAIN_SRC="$(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "
  SELECT count(*) FROM media_revisions r
  JOIN dives d ON d.video_uuid = r.video_uuid
  JOIN user_diver_access a ON a.diver_id = d.diver_id AND a.access_kind = 'OWNER'
  JOIN app_users u ON u.id = a.user_id AND u.is_active;")"
if [ "$CHAIN" != "$CHAIN_SRC" ]; then
  echo "[restore-test] MISMATCH ownership chain: source=$CHAIN_SRC restored=$CHAIN"
  FAIL=1
fi
LOCS="$(docker exec "$RESTORE_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
  "SELECT count(*) FROM media_blob_locations WHERE environment='prod' AND verified;")"
echo "[restore-test] verified PROD media_blob_locations restored: $LOCS"

T_END=$(date +%s)
if [ "$FAIL" -eq 0 ]; then
  echo "[restore-test] PASS total=$((T_END-T0))s decrypt=$((T_DECRYPT-T0))s restore=$((T_RESTORE-T1))s"
  exit 0
else
  echo "[restore-test] FAIL total=$((T_END-T0))s"
  exit 1
fi
