#!/usr/bin/env sh
set -eu

CONFIG_FILE="${1:-/home/mcauchy/dive-analyser/ops/icloud-video-sync.env}"
if [ -f "$CONFIG_FILE" ]; then
  # shellcheck disable=SC1090
  . "$CONFIG_FILE"
fi

APP_VIDEO_CACHE="${APP_VIDEO_CACHE:-/home/mcauchy/dive-analyser/media/videos}"
VIDEO_CACHE_RETENTION_DAYS="${VIDEO_CACHE_RETENTION_DAYS:-90}"
VIDEO_CACHE_MAX_BYTES="${VIDEO_CACHE_MAX_BYTES:-53687091200}"

mkdir -p "$APP_VIDEO_CACHE"

find "$APP_VIDEO_CACHE" -type f \
  \( -iname '*.mov' -o -iname '*.mp4' -o -iname '*.m4v' \) \
  -mtime +"$VIDEO_CACHE_RETENTION_DAYS" \
  -print -delete

current_bytes="$(du -sb "$APP_VIDEO_CACHE" | awk '{print $1}')"
if [ "$current_bytes" -le "$VIDEO_CACHE_MAX_BYTES" ]; then
  exit 0
fi

find "$APP_VIDEO_CACHE" -type f \
  \( -iname '*.mov' -o -iname '*.mp4' -o -iname '*.m4v' \) \
  -printf '%T@ %p\n' |
  sort -n |
  while IFS= read -r line; do
    file="${line#* }"
    [ -f "$file" ] || continue
    rm -f "$file"
    current_bytes="$(du -sb "$APP_VIDEO_CACHE" | awk '{print $1}')"
    [ "$current_bytes" -le "$VIDEO_CACHE_MAX_BYTES" ] && break
  done
