#!/bin/sh
set -eu
# Empty disables signing; reject config syntax injection from the environment.
if [ -n "${MEDIA_SIGNING_SECRET:-}" ]; then
  test "${#MEDIA_SIGNING_SECRET}" = 64
  case "$MEDIA_SIGNING_SECRET" in *[!0-9a-f]*) exit 1 ;; esac
fi
