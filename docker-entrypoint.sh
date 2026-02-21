#!/bin/sh
set -eu

TARGET_PATH="${KRILL_BRAINDUMP_PATH:-/app/data/braindump.json}"
TARGET_DIR="$(dirname "$TARGET_PATH")"
BOOTSTRAP_PATH="${KRILL_BOOTSTRAP_PATH:-/bootstrap/braindump.json}"

mkdir -p "$TARGET_DIR"

if [ ! -f "$TARGET_PATH" ] && [ -f "$BOOTSTRAP_PATH" ]; then
  cp "$BOOTSTRAP_PATH" "$TARGET_PATH"
fi

exec "$@"
