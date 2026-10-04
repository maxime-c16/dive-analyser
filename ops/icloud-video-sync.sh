#!/usr/bin/env sh
# set -eu  # intentionally permissive: icloudpd downloads can take hours

CONFIG_FILE="${1:-/home/mcauchy/dive-analyser/ops/icloud-video-sync.env}"
if [ -f "$CONFIG_FILE" ]; then
  . "$CONFIG_FILE"
fi

ICLOUDPD_CONTAINER="${ICLOUDPD_CONTAINER:-icloudpd}"
ICLOUDPD_DOWNLOAD_ROOT="${ICLOUDPD_DOWNLOAD_ROOT:-/home/mcauchy/icloudpd/downloads}"
ICLOUDPD_USER="${ICLOUDPD_USER:-maxime.cauchy93@gmail.com}"
ICLOUDPD_ALBUM="${ICLOUDPD_ALBUM:-}"
ICLOUDPD_RECENT="${ICLOUDPD_RECENT:-2000}"
ICLOUDPD_UNTIL_FOUND="${ICLOUDPD_UNTIL_FOUND:-500}"
ICLOUDPD_SKIP_CREATED_BEFORE="${ICLOUDPD_SKIP_CREATED_BEFORE:-}"
ICLOUDPD_SIZE="${ICLOUDPD_SIZE:-original}"
VIDEO_MIN_SIZE_BYTES="${VIDEO_MIN_SIZE_BYTES:-10485760}"
APP_VIDEO_CACHE="${APP_VIDEO_CACHE:-/home/mcauchy/dive-analyser/media/videos}"

mkdir -p "$ICLOUDPD_DOWNLOAD_ROOT" "$APP_VIDEO_CACHE"
touch "$ICLOUDPD_DOWNLOAD_ROOT/.mounted"

ALBUM_ARG=""
if [ -n "$ICLOUDPD_ALBUM" ]; then
  ALBUM_ARG="--album \"$ICLOUDPD_ALBUM\""
fi

SKIP_CREATED_ARG=""
if [ -n "$ICLOUDPD_SKIP_CREATED_BEFORE" ]; then
  SKIP_CREATED_ARG="--skip-created-before $ICLOUDPD_SKIP_CREATED_BEFORE"
fi

echo "[icloud-video-sync] Starting download at $(date)"
docker exec "$ICLOUDPD_CONTAINER" \
  /opt/icloudpd/bin/icloudpd \
    --username "$ICLOUDPD_USER" \
    --cookie-directory /config \
    --domain com \
    --directory /icloud \
    --skip-photos \
    --skip-live-photos \
    --size "$ICLOUDPD_SIZE" \
    --recent "$ICLOUDPD_RECENT" \
    --until-found "$ICLOUDPD_UNTIL_FOUND" \
    $SKIP_CREATED_ARG \
    --folder-structure "{:%Y/%m/%d}" \
    --file-match-policy name-size-dedup-with-suffix \
    $ALBUM_ARG \
    2>&1 || echo "[icloud-video-sync] icloudpd exited with code $? (may be partial)"
echo "[icloud-video-sync] Download phase done at $(date)"

echo "[icloud-video-sync] Copying videos >= ${VIDEO_MIN_SIZE_BYTES} bytes to app cache..."
find "$ICLOUDPD_DOWNLOAD_ROOT" -type f \
  \( -iname '*.mov' -o -iname '*.mp4' -o -iname '*.m4v' \) \
  ! -name '*.part' \
  -size +"${VIDEO_MIN_SIZE_BYTES}c" \
  -exec cp -n {} "$APP_VIDEO_CACHE/" \;
echo "[icloud-video-sync] Copied $(ls "$APP_VIDEO_CACHE" 2>/dev/null | wc -l) files to app cache"

echo "[icloud-video-sync] Running cache prune..."
/home/mcauchy/dive-analyser/ops/icloud-video-cache-prune.sh "$CONFIG_FILE" || true
echo "[icloud-video-sync] Done at $(date)"
