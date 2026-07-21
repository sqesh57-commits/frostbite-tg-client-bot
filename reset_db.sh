#!/bin/bash
# Reset bot database
# Usage: bash reset_db.sh

CONTAINER="frostbite-tg-client-bot"

echo "=== Reset bot database ==="

# Find actual DB path inside container
DB_PATH=$(docker exec "$CONTAINER" python3 -c "import os; print(os.getenv('DB_PATH', '/app/data/users.db'))" 2>/dev/null || echo "/app/data/users.db")
echo "DB_PATH inside container: $DB_PATH"

# Find host path via mount
HOST_PATH=$(docker inspect "$CONTAINER" --format '{{range .Mounts}}{{if eq .Destination "'"$DB_PATH"'"}}{{.Source}}{{end}}{{end}}' 2>/dev/null)
echo "Host mount: $HOST_PATH"

if [[ -n "$HOST_PATH" ]]; then
    echo "Removing: $HOST_PATH/users.db"
    rm -f "$HOST_PATH/users.db"
elif [[ -d "/home/sqesh/frostbite-tg-client-bot/data" ]]; then
    echo "Trying known path: /home/sqesh/frostbite-tg-client-bot/data/users.db"
    rm -f /home/sqesh/frostbite-tg-client-bot/data/users.db
else
    echo "ERROR: Could not find DB file. Manual removal needed:"
    echo "  docker exec $CONTAINER rm -f $DB_PATH"
    exit 1
fi

# Restart bot
echo "Restarting bot..."
docker restart "$CONTAINER"

echo "=== Done ==="
sleep 3
docker logs "$CONTAINER" --tail 5
