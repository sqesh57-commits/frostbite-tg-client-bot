#!/bin/bash
# Reset bot database — drops all users, profiles, orders
# Usage: bash reset_db.sh

set -e

DB_PATH="${1:-/app/data/users.db}"
CONTAINER="frostbite-tg-client-bot"

echo "=== Reset bot database ==="
echo "Container: $CONTAINER"
echo "DB path: $DB_PATH"

# Stop bot first
echo "Stopping bot..."
docker stop "$CONTAINER" 2>/dev/null || true

# Drop tables
echo "Dropping tables..."
docker exec "$CONTAINER" python3 -c "
import os, sys
sys.path.insert(0, '/app/src')
os.environ['DB_PATH'] = '$DB_PATH'
from database import engine, Base
from sqlalchemy import text
with engine.connect() as conn:
    conn.execute(text('DROP TABLE IF EXISTS orders'))
    conn.execute(text('DROP TABLE IF EXISTS vpn_profiles'))
    conn.execute(text('DROP TABLE IF EXISTS users'))
    conn.commit()
print('Tables dropped')
" 2>/dev/null || {
    # Fallback: direct sqlite3
    echo "Trying sqlite3 fallback..."
    docker exec "$CONTAINER" sqlite3 "$DB_PATH" "
        DROP TABLE IF EXISTS orders;
        DROP TABLE IF EXISTS vpn_profiles;
        DROP TABLE IF EXISTS users;
    " 2>/dev/null || {
        echo "Removing DB file entirely..."
        docker exec "$CONTAINER" rm -f "$DB_PATH"
    }
}

# Start bot
echo "Starting bot..."
docker start "$CONTAINER"

echo "=== Done ==="
echo "Bot will recreate tables on next request."
echo "Test: /start → /connect"
