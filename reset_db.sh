#!/usr/bin/env bash
# Reset the bot SQLite database inside the Docker container.
# Intended for test environments only: removes users.db and restarts the bot so
# SQLAlchemy recreates an empty schema on startup.
#
# Usage:
#   ./reset_db.sh
#   ./reset_db.sh --container frostbite-tg-client-bot --db-path /app/data/users.db
#   ./reset_db.sh --purge-xui
#
# Environment overrides:
#   CONTAINER_NAME - Docker container name (default: frostbite-tg-client-bot)
#   DB_PATH        - SQLite DB path inside the container. If omitted, the script
#                    reads DB_PATH from the container environment and falls back
#                    to /app/data/users.db.

set -euo pipefail

CONTAINER="${CONTAINER_NAME:-frostbite-tg-client-bot}"
DB_PATH_OVERRIDE="${DB_PATH:-}"
PURGE_XUI=false

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

resolve_host_db_path() {
    docker inspect "$CONTAINER" | DB_PATH_IN_CONTAINER="$DB_PATH_IN_CONTAINER" python3 -c '
import json
import os
import pathlib
import sys

db_path = pathlib.PurePosixPath(os.environ["DB_PATH_IN_CONTAINER"])
container = json.load(sys.stdin)[0]
mounts = sorted(
    container.get("Mounts", []),
    key=lambda mount: len(mount.get("Destination", "")),
    reverse=True,
)
for mount in mounts:
    destination = mount.get("Destination") or ""
    source = mount.get("Source") or ""
    if not destination or not source:
        continue
    dest_path = pathlib.PurePosixPath(destination)
    try:
        relative = db_path.relative_to(dest_path)
    except ValueError:
        continue
    print(pathlib.Path(source, *relative.parts))
    break
'
}

print_user_count() {
    local label="$1"
    docker exec \
        -e DB_PATH_TO_RESET="$DB_PATH_IN_CONTAINER" \
        -e RESET_DB_COUNT_LABEL="$label" \
        "$CONTAINER" \
        python3 - <<'PY'
import os
import sqlite3

db_path = os.environ["DB_PATH_TO_RESET"]
label = os.environ.get("RESET_DB_COUNT_LABEL", "Users")
if not os.path.exists(db_path):
    print(f"{label}: DB file does not exist")
else:
    try:
        with sqlite3.connect(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        print(f"{label}: {count} user(s) in {db_path}")
    except sqlite3.Error as exc:
        print(f"{label}: cannot read users table in {db_path}: {exc}")
PY
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
        --purge-xui)
            PURGE_XUI=true
            shift
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
if [[ "$PURGE_XUI" == "true" ]]; then
    echo "3x-ui:     purge bot clients listed in the current DB before deleting it"
fi
echo "WARNING: this permanently deletes the bot test database and SQLite sidecar files."

if [[ "$PURGE_XUI" == "true" ]]; then
    echo "Deleting matching bot clients from 3x-ui before DB reset..."
    docker exec \
        -e DB_PATH_TO_RESET="$DB_PATH_IN_CONTAINER" \
        "$CONTAINER" \
        python3 - <<'PY'
import asyncio
import json
import os
import sqlite3

from functions import XUIAPI, build_bot_profile_name

DB_PATH = os.environ["DB_PATH_TO_RESET"]


def add_candidate(candidates, value):
    if value and value not in candidates:
        candidates.append(value)


def get_candidates():
    if not os.path.exists(DB_PATH):
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT telegram_id, username, full_name, vless_profile_data FROM users"
        ).fetchall()
    finally:
        conn.close()

    candidates = []
    for row in rows:
        profile_data = {}
        if row["vless_profile_data"]:
            try:
                profile_data = json.loads(row["vless_profile_data"])
            except Exception:
                profile_data = {}

        add_candidate(candidates, profile_data.get("email"))
        add_candidate(candidates, build_bot_profile_name(row["telegram_id"], row["username"]))
        add_candidate(candidates, build_bot_profile_name(row["telegram_id"], None))
        add_candidate(candidates, row["full_name"])
        add_candidate(candidates, row["full_name"].replace(" ", "_") if row["full_name"] else None)

    return candidates


async def main():
    candidates = get_candidates()
    if not candidates:
        print("No users or 3x-ui client candidates found in DB")
        return

    api = XUIAPI()
    deleted = 0
    try:
        for email in candidates:
            client = await api.get_client(email)
            if not client:
                print(f"Skip missing 3x-ui client: {email}")
                continue
            if await api.delete_client(email):
                deleted += 1
                print(f"Deleted 3x-ui client: {email}")
            else:
                print(f"Failed to delete 3x-ui client: {email}")
    finally:
        await api.close()

    print(f"Deleted {deleted} 3x-ui client(s)")


asyncio.run(main())
PY
fi

print_user_count "Before reset"

HOST_DB_PATH=$(resolve_host_db_path)
if [[ -n "$HOST_DB_PATH" ]]; then
    echo "Host DB path: $HOST_DB_PATH"
    echo "Stopping container before deleting the bind-mounted SQLite file..."
    docker stop "$CONTAINER" >/dev/null
    mkdir -p "$(dirname "$HOST_DB_PATH")"
    rm -f "$HOST_DB_PATH" "$HOST_DB_PATH-wal" "$HOST_DB_PATH-shm" "$HOST_DB_PATH-journal"
    echo "Removed $HOST_DB_PATH and SQLite sidecar files if they existed"
    echo "Starting container to recreate an empty database..."
    docker start "$CONTAINER" >/dev/null
else
    echo "No host bind mount found for DB path; deleting inside the running container."
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
fi

echo "=== Done ==="
echo "Waiting for database initialization..."
sleep 3
print_user_count "After reset"
echo "Recent logs:"
docker logs "$CONTAINER" --tail 10
