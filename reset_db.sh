#!/bin/bash
# Reset bot database — drops all users, profiles, orders
# Usage: bash reset_db.sh

set -e

CONTAINER="frostbite-tg-client-bot"
DB_PATH="/app/data/users.db"

echo "=== Reset bot database ==="

# 1. Stop bot
echo "1. Stopping bot..."
docker stop "$CONTAINER" 2>/dev/null || true

# 2. Remove DB file directly from host (volume mount)
echo "2. Removing database..."
HOST_DB=$(docker inspect "$CONTAINER" --format '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{.Source}}{{end}}{{end}}' 2>/dev/null)
if [[ -n "$HOST_DB" ]]; then
    echo "   Host DB path: $HOST_DB/users.db"
    rm -f "$HOST_DB/users.db"
    echo "   Removed"
else
    echo "   Could not find host path, trying docker volume..."
    docker run --rm -v frostbite-tg-client-bot_data:/data alpine rm -f /data/users.db 2>/dev/null || true
fi

# 3. Start bot — it will recreate tables
echo "3. Starting bot..."
docker start "$CONTAINER"

echo "=== Done ==="
echo "Bot will recreate tables on first request."
echo "Test: /start → /connect"
