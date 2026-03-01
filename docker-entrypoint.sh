#!/bin/sh
set -eu

TARGET_PATH="${KRILL_BRAINDUMP_PATH:-/app/data/braindump.db}"
TARGET_DIR="$(dirname "$TARGET_PATH")"
BOOTSTRAP_PATH="${KRILL_BOOTSTRAP_PATH:-/bootstrap/braindump.db}"

mkdir -p "$TARGET_DIR"

if [ ! -f "$TARGET_PATH" ] && [ -f "$BOOTSTRAP_PATH" ]; then
  cp "$BOOTSTRAP_PATH" "$TARGET_PATH"
fi

ENABLE_XVFB="${KRILL_ENABLE_XVFB:-1}"
if [ "$ENABLE_XVFB" = "1" ] || [ "$ENABLE_XVFB" = "true" ] || [ "$ENABLE_XVFB" = "TRUE" ]; then
  DISPLAY_VALUE="${DISPLAY:-:99}"
  export DISPLAY="$DISPLAY_VALUE"
  Xvfb "$DISPLAY_VALUE" -screen 0 1366x768x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
fi

exec "$@"
