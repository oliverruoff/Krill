#!/bin/bash

set -euo pipefail

CONTAINER_NAME="krill-app"
IMAGE_NAME="ghcr.io/oliverruoff/krill:latest"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="${PWD}/backups"
BACKUP_FILE="${BACKUP_DIR}/braindump.db"

# You can override this when running the script, e.g.:
# KRILL_PUBLIC_BASE_URL="https://krill.example.com" ./scripts/update-krill.sh
: "${KRILL_PUBLIC_BASE_URL:=}"

mkdir -p "$BACKUP_DIR"

echo "💾 Versucht braindump.db aus dem laufenden Container zu sichern..."
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  if docker cp "${CONTAINER_NAME}:/app/data/braindump.db" "$BACKUP_FILE"; then
    echo "✅ Backup erstellt: $BACKUP_FILE"
  else
    echo "⚠️ Konnte braindump.db nicht sichern (fahre trotzdem fort)."
  fi
else
  echo "ℹ️ Kein bestehender Container gefunden, kein Backup notwendig."
fi

echo "🚀 Zieht das neueste Image von GitHub..."
docker pull "$IMAGE_NAME"

echo "🛑 Stoppt den alten Container (falls er läuft)..."
# '|| true' verhindert, dass das Skript abbricht, falls der Container mal nicht existiert
docker stop "$CONTAINER_NAME" || true

echo "🗑️ Löscht den alten Container..."
docker rm "$CONTAINER_NAME" || true

echo "✨ Startet den neuen Container..."
ENV_ARGS=()
if [ -n "$KRILL_PUBLIC_BASE_URL" ]; then
  ENV_ARGS+=("-e" "KRILL_PUBLIC_BASE_URL=$KRILL_PUBLIC_BASE_URL")
  echo "🌐 Nutze KRILL_PUBLIC_BASE_URL=$KRILL_PUBLIC_BASE_URL"
else
  echo "ℹ️ KRILL_PUBLIC_BASE_URL nicht gesetzt (verwende Request-Host zur Callback-Ermittlung)."
fi

docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  -v /etc/localtime:/etc/localtime:ro \
  -v /etc/timezone:/etc/timezone:ro \
  -p 80:8055 \
  "${ENV_ARGS[@]}" \
  "$IMAGE_NAME"

if [ -f "$BACKUP_FILE" ]; then
  echo "📥 Stellt braindump.db im neuen Container wieder her..."
  if docker cp "$BACKUP_FILE" "${CONTAINER_NAME}:/app/data/braindump.db"; then
    echo "✅ braindump.db wiederhergestellt."
    echo "🔄 Starte Container neu, damit die DB sicher neu geladen wird..."
    docker restart "$CONTAINER_NAME" >/dev/null
  else
    echo "⚠️ Wiederherstellung der braindump.db fehlgeschlagen."
  fi
fi

echo "🧹 Räumt alte, ungenutzte Images auf..."
docker image prune -f

echo "✅ Update abgeschlossen! Krill ist wieder online."
