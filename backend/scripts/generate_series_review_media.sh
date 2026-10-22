#!/usr/bin/env bash
# Synthetic review-only footage. These outputs are ignored by Git.
set -euo pipefail
series_repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
command -v ffmpeg >/dev/null || { echo "Install ffmpeg to generate the review clips." >&2; exit 1; }
mkdir -p "$series_repo/frontend/public"
ffmpeg -hide_banner -loglevel error -f lavfi -i "testsrc2=size=${SERIES_REVIEW_SIZE:-360x640}:rate=24" \
  -t 2 -c:v libx264 -pix_fmt yuv420p -movflags +faststart -y \
  "$series_repo/frontend/public/series-review-demo.mp4"
ffmpeg -hide_banner -loglevel error -i "$series_repo/frontend/public/series-review-demo.mp4" \
  -frames:v 1 -update 1 -y "$series_repo/frontend/public/series-review-demo.jpg"
echo "Generated synthetic series-review video and poster."
