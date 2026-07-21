#!/usr/bin/env bash
# Reset the bot SQLite database inside the Docker container.
# Intended for test environments only: removes users.db and restarts the bot so
# SQLAlchemy recreates an empty schema on startup.
#
# Usage:
#   ./reset_db.sh
#   ./reset_db.sh --container frostbite-tg-client-bot --db-path /app/data/users.db
#
# Environment overrides:
#   CONTAINER_NAME - Docker container name (default: frostbite-tg-client-bot)
#   DB_PATH        - SQLite DB path inside the container. If omitted, the script
#                    reads DB_PATH from the container environment and falls back
#                    to /app/data/users.db.

set -euo pipefail

CONTAINER="${CONTAINER_NAME:-frostbite-tg-client-bot}"
DB_PATH_OVERRIDE="${DB_PATH:-}"

usage() {
    awk '
        NR == 1 { next }
        /^#($| )/ { sub(/^# ?/, ""); print; next }
        { exit }
    ' "$0"
}

require_value() {
    local option="$1"
    local value="${2:-}"
    if [[ -z "$value" ]]; then
        echo "ERROR: $option requires a value" >&2
        usage >&2
        exit 2
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --container)
            require_value "$1" "${2:-}"
            CONTAINER="$2"
            shift 2
            ;;
        --db-path)
            require_value "$1" "${2:-}"
            DB_PATH_OVERRIDE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -z "$CONTAINER" ]]; then
    echo "ERROR: container name is empty" >&2
    exit 2
fi

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "ERROR: Docker container '$CONTAINER' was not found" >&2
    exit 1
fi

if [[ -n "$DB_PATH_OVERRIDE" ]]; then
    DB_PATH_IN_CONTAINER="$DB_PATH_OVERRIDE"
else
    DB_PATH_IN_CONTAINER=$(docker exec "$CONTAINER" sh -c 'printf "%s" "${DB_PATH:-/app/data/users.db}"')
fi

if [[ -z "$DB_PATH_IN_CONTAINER" || "$DB_PATH_IN_CONTAINER" != /* ]]; then
    echo "ERROR: DB path must be an absolute path inside the container, got: '$DB_PATH_IN_CONTAINER'" >&2
    exit 2
fi

case "$DB_PATH_IN_CONTAINER" in
    */users.db) ;;
    *)
        echo "ERROR: refusing to remove an unexpected DB path: '$DB_PATH_IN_CONTAINER'" >&2
        echo "Pass a path ending with /users.db to confirm the target." >&2
        exit 2
        ;;
esac

echo "=== Reset bot database ==="
echo "Container: $CONTAINER"
echo "Database:  $DB_PATH_IN_CONTAINER"
echo "WARNING: this permanently deletes the bot test database and SQLite sidecar files."

docker exec \
    -e DB_PATH_TO_RESET="$DB_PATH_IN_CONTAINER" \
    "$CONTAINER" \
    sh -eu -c '
        db="$DB_PATH_TO_RESET"
        dir=$(dirname "$db")
        mkdir -p "$dir"
        rm -f "$db" "$db-wal" "$db-shm" "$db-journal"
        echo "Removed $db and SQLite sidecar files if they existed"
    '

echo "Restarting container to recreate an empty database..."
docker restart "$CONTAINER" >/dev/null

echo "=== Done ==="
echo "Recent logs:"
sleep 3
docker logs "$CONTAINER" --tail 10
