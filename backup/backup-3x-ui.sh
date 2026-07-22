#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/backup-3x-ui.env"

[ -f "$ENV_FILE" ] || {
  echo "[ERROR] Config not found: $ENV_FILE"
  exit 1
}

# shellcheck source=/dev/null
source "$ENV_FILE"

DATE="$(date +'%Y-%m-%d_%H-%M-%S')"
ARCHIVE_NAME="3x-ui-backup_${DATE}.tar.gz"
ARCHIVE_PATH="${BACKUP_DIR}/${ARCHIVE_NAME}"
SHA256_PATH="${ARCHIVE_PATH}.sha256"
RESTORE_INFO="restore-info_${DATE}.txt"
RESTORE_INFO_PATH="${BACKUP_DIR}/${RESTORE_INFO}"
LOG_FILE="${BACKUP_DIR}/backup.log"

LOCAL_STATUS="SKIP"
RPI_STATUS="SKIP"
GDRIVE_STATUS="SKIP"
LOCAL_DELETED="0"
RPI_DELETED="0"
GDRIVE_DELETED="0"
CONTAINER_STATUS="UNKNOWN"
ARCHIVE_STATUS="UNKNOWN"
SHA256_STATUS="UNKNOWN"
START_TS="$(date +%s)"
WAS_RUNNING="false"
CONTAINER_STOPPED_BY_SCRIPT="false"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

exec >> "$LOG_FILE" 2>&1

log() {
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

send_telegram() {
  local text="$1"

  if [ "${ENABLE_TELEGRAM:-false}" != "true" ]; then
    return 0
  fi

  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    log "[WARN] Telegram enabled but token/chat_id is empty"
    return 0
  fi

  curl -sS \
    -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${text}" \
    -d "parse_mode=HTML" \
    >/dev/null || log "[WARN] Telegram send failed"
}

finish_report() {
  local result="$1"
  local end_ts duration size sha_short result_line result_icon
  end_ts="$(date +%s)"
  duration="$((end_ts - START_TS)) sec"

  if [ "$result" = "OK" ]; then
    result_icon="✅"
    result_line="Backup выполнен успешно"
  else
    result_icon="🔴"
    result_line="Backup FAILED"
  fi

  if [ -f "$ARCHIVE_PATH" ]; then
    size="$(du -h "$ARCHIVE_PATH" | awk '{print $1}')"
  else
    size="n/a"
  fi

  if [ -f "$SHA256_PATH" ]; then
    sha_short="$(cut -d ' ' -f1 "$SHA256_PATH" | cut -c1-12)"
  else
    sha_short="n/a"
  fi

  local report
  report="$(cat <<EOF
🦞 <b>3x-ui Backup</b>

${result_icon} <b>${result_line}</b>

🖥 <b>Host</b>
$(hostname)

📦 <b>Archive</b>
${ARCHIVE_NAME}

📏 <b>Size</b>
${size}

🔐 <b>SHA256</b>
${sha_short}...

📊 <b>Checks</b>
Container: ${CONTAINER_STATUS}
Archive: ${ARCHIVE_STATUS}
SHA256: ${SHA256_STATUS}

💾 <b>Storage</b>
Local: ${LOCAL_STATUS}
Raspberry Pi: ${RPI_STATUS}
Google Drive: ${GDRIVE_STATUS}

🗑 <b>Retention</b>
Local deleted: ${LOCAL_DELETED}
RPi deleted: ${RPI_DELETED}
GDrive deleted: ${GDRIVE_DELETED}

⏱ <b>Duration</b>
${duration}

📄 <b>Details</b>
${RESTORE_INFO}
EOF
)"
  send_telegram "$report"
}

FINAL_REPORT_SENT="false"

finish_report_once() {
  local result="$1"

  if [ "$FINAL_REPORT_SENT" = "true" ]; then
    return 0
  fi

  FINAL_REPORT_SENT="true"
  finish_report "$result"
}

cleanup() {
  local exit_code=$?

  if [ "$CONTAINER_STOPPED_BY_SCRIPT" = "true" ]; then
    log "[WARN] Container was stopped by script. Trying to start it before exit..."
    cd "$PROJECT_DIR" 2>/dev/null || true
    docker compose up -d "$CONTAINER_NAME" || true

    if wait_container_running 60; then
      CONTAINER_STATUS="OK_RECOVERED"
      CONTAINER_STOPPED_BY_SCRIPT="false"
      log "[OK] Container recovered after script exit"
    else
      CONTAINER_STATUS="FAIL_RECOVER"
      log "[ERROR] Container recovery failed"
    fi
  fi

  if [ "$exit_code" -ne 0 ]; then
    finish_report_once "FAILED"
  fi

  exit "$exit_code"
}

fail() {
  log "[ERROR] $*"
  exit 1
}

trap cleanup EXIT

wait_container_stopped() {
  local timeout="${1:-30}"
  local elapsed=0
  local state

  while [ "$elapsed" -lt "$timeout" ]; do
    state="$(docker inspect -f '{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || true)"

    if [ "$state" = "exited" ] || [ "$state" = "created" ]; then
      return 0
    fi

    sleep 1
    elapsed=$((elapsed + 1))
  done

  return 1
}

wait_container_running() {
  local timeout="${1:-60}"
  local elapsed=0
  local state health

  while [ "$elapsed" -lt "$timeout" ]; do
    state="$(docker inspect -f '{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || true)"
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER_NAME" 2>/dev/null || true)"

    if [ "$state" = "running" ]; then
      log "[INFO] Container state: running, health: $health"
      return 0
    fi

    sleep 1
    elapsed=$((elapsed + 1))
  done

  return 1
}

check_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

log "========== 3x-ui backup v2 started =========="

check_command docker
check_command tar
check_command sha256sum
check_command curl

if [ "${ENABLE_RPI_UPLOAD:-false}" = "true" ]; then
  check_command rsync
  check_command ssh
fi

if [ "${ENABLE_GDRIVE_UPLOAD:-false}" = "true" ]; then
  check_command rclone
fi

[ -d "$PROJECT_DIR" ] || fail "Project dir not found: $PROJECT_DIR"

cd "$PROJECT_DIR"

[ -f "compose.yml" ] || fail "compose.yml not found"
[ -f ".env" ] || fail ".env not found"
[ -d "data/x-ui" ] || fail "data/x-ui not found"
[ -f "data/x-ui/x-ui.db" ] || fail "data/x-ui/x-ui.db not found"
[ -d "nginx" ] || fail "nginx dir not found"
[ -d "certs" ] || fail "certs dir not found"

docker compose ps >/dev/null 2>&1 || fail "docker compose is not working in $PROJECT_DIR"

current_state="$(docker inspect -f '{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || true)"

if [ "$current_state" = "running" ]; then
  WAS_RUNNING="true"
  log "[INFO] Stopping container for consistent SQLite backup..."
  docker compose stop "$CONTAINER_NAME"
  CONTAINER_STOPPED_BY_SCRIPT="true"

  wait_container_stopped 30 || fail "Container did not stop within timeout"
  log "[OK] Container stopped"
else
  log "[INFO] Container is not running, current state: ${current_state:-unknown}"
fi

log "[INFO] Creating restore info..."

cat > "$RESTORE_INFO_PATH" <<EOF
Backup date: ${DATE}
Host: $(hostname)
Project dir: ${PROJECT_DIR}
Container: ${CONTAINER_NAME}
Archive: ${ARCHIVE_NAME}
Created by: backup-3x-ui.sh v2

Restore:
  cd ${PROJECT_DIR}
  docker compose down
  tar -xzf ${ARCHIVE_NAME}
  docker compose up -d --build

Check:
  docker ps
  docker logs --tail=100 ${CONTAINER_NAME}
EOF

log "[INFO] Creating archive: $ARCHIVE_PATH"

tar \
  --exclude='data/log/*' \
  --exclude='.git' \
  --exclude='*.tmp' \
  -czf "$ARCHIVE_PATH" \
  compose.yml \
  Dockerfile \
  docker \
  nginx \
  data/x-ui \
  certs \
  .env \
  backup-3x-ui.sh \
  backup-3x-ui.env \
  -C "$BACKUP_DIR" "$RESTORE_INFO" \
  2>/tmp/3x-ui-backup-tar-error.log

if [ "$?" -ne 0 ]; then
  cat /tmp/3x-ui-backup-tar-error.log
  fail "tar archive creation failed"
fi

chmod 600 "$ARCHIVE_PATH"

log "[INFO] Verifying archive..."

tar -tzf "$ARCHIVE_PATH" >/dev/null || fail "Archive verification failed"

ARCHIVE_SIZE_BYTES="$(stat -c%s "$ARCHIVE_PATH")"

if [ "$ARCHIVE_SIZE_BYTES" -lt 10240 ]; then
  fail "Archive is too small: ${ARCHIVE_SIZE_BYTES} bytes"
fi

ARCHIVE_STATUS="OK"
LOCAL_STATUS="OK"
log "[OK] Archive verified"

log "[INFO] Creating sha256..."

sha256sum "$ARCHIVE_PATH" > "$SHA256_PATH"
chmod 600 "$SHA256_PATH"
SHA256_STATUS="OK"

if [ "$WAS_RUNNING" = "true" ]; then
  log "[INFO] Starting container back..."
  docker compose up -d "$CONTAINER_NAME"

  wait_container_running 60 || fail "Container did not start within timeout"

  CONTAINER_STOPPED_BY_SCRIPT="false"
  CONTAINER_STATUS="OK"
  log "[OK] Container started"
  if docker exec "$CONTAINER_NAME" nginx -t >/dev/null 2>&1; then
    log "[OK] nginx config is valid"
  else
    log "[WARN] nginx config check failed"
  fi
else
  CONTAINER_STATUS="SKIP"
fi

if [ "${ENABLE_RPI_UPLOAD:-false}" = "true" ]; then
  log "[INFO] Checking Raspberry Pi target..."

  if timeout 30 ssh \
    -i "$RPI_IDENTITY_FILE" \
    -p "$RPI_PORT" \
    -o BatchMode=yes \
    -o ConnectTimeout=10 \
    "${RPI_USER}@${RPI_HOST}" \
    "mkdir -p '$RPI_TARGET_DIR' && test -w '$RPI_TARGET_DIR'"; then

    log "[INFO] Uploading archive to Raspberry Pi..."

    if timeout 300 rsync -avz \
      -e "ssh -i $RPI_IDENTITY_FILE -p $RPI_PORT -o BatchMode=yes -o ConnectTimeout=10" \
      "$ARCHIVE_PATH" "$SHA256_PATH" \
      "${RPI_USER}@${RPI_HOST}:${RPI_TARGET_DIR}/"; then

      if timeout 30 ssh \
        -i "$RPI_IDENTITY_FILE" \
        -p "$RPI_PORT" \
        -o BatchMode=yes \
        "${RPI_USER}@${RPI_HOST}" \
        "test -f '${RPI_TARGET_DIR}/${ARCHIVE_NAME}' && test -f '${RPI_TARGET_DIR}/${ARCHIVE_NAME}.sha256'"; then
        RPI_STATUS="OK"
        log "[OK] Raspberry Pi upload verified"
      else
        RPI_STATUS="FAIL_VERIFY"
        log "[WARN] Raspberry Pi upload verification failed"
      fi

      log "[INFO] Cleaning old Raspberry Pi backups..."
      RPI_DELETED="$(timeout 30 ssh \
        -i "$RPI_IDENTITY_FILE" \
        -p "$RPI_PORT" \
        -o BatchMode=yes \
        "${RPI_USER}@${RPI_HOST}" \
        "find '$RPI_TARGET_DIR' -type f \( -name '3x-ui-backup_*.tar.gz' -o -name '3x-ui-backup_*.tar.gz.sha256' \) -mtime +${RETENTION_RPI_DAYS} -print | wc -l" \
        2>/dev/null || echo 0)"

      timeout 30 ssh \
        -i "$RPI_IDENTITY_FILE" \
        -p "$RPI_PORT" \
        -o BatchMode=yes \
        "${RPI_USER}@${RPI_HOST}" \
        "find '$RPI_TARGET_DIR' -type f \( -name '3x-ui-backup_*.tar.gz' -o -name '3x-ui-backup_*.tar.gz.sha256' \) -mtime +${RETENTION_RPI_DAYS} -delete" \
        || log "[WARN] Raspberry Pi retention cleanup failed"

    else
      RPI_STATUS="FAIL_UPLOAD"
      log "[WARN] Raspberry Pi upload failed"
    fi
  else
    RPI_STATUS="FAIL_CONNECT"
    log "[WARN] Raspberry Pi target is not available"
  fi
fi

if [ "${ENABLE_GDRIVE_UPLOAD:-false}" = "true" ]; then
  log "[INFO] Uploading archive to Google Drive..."

  if timeout 600 rclone copy "$ARCHIVE_PATH" "${GDRIVE_REMOTE}:${GDRIVE_PATH}/" \
    && timeout 600 rclone copy "$SHA256_PATH" "${GDRIVE_REMOTE}:${GDRIVE_PATH}/"; then
    if rclone lsf "${GDRIVE_REMOTE}:${GDRIVE_PATH}/" --files-only | grep -Fxq "$ARCHIVE_NAME"; then
      GDRIVE_STATUS="OK"
      log "[OK] Google Drive upload verified"
    else
      GDRIVE_STATUS="FAIL_VERIFY"
      log "[WARN] Google Drive upload verification failed"
    fi

    log "[INFO] Cleaning old Google Drive backups..."
    GDRIVE_DELETED="$(rclone lsf "${GDRIVE_REMOTE}:${GDRIVE_PATH}/" \
      --files-only \
      --min-age "${RETENTION_GDRIVE_DAYS}d" \
      --include "3x-ui-backup_*.tar.gz" \
      --include "3x-ui-backup_*.tar.gz.sha256" \
      2>/dev/null | wc -l)"
    timeout 300 rclone delete \
      --min-age "${RETENTION_GDRIVE_DAYS}d" \
      --include "3x-ui-backup_*.tar.gz" \
      --include "3x-ui-backup_*.tar.gz.sha256" \
      "${GDRIVE_REMOTE}:${GDRIVE_PATH}/" \
      || log "[WARN] Google Drive retention cleanup failed"
  else
    GDRIVE_STATUS="FAIL_UPLOAD"
    log "[WARN] Google Drive upload failed"
  fi
fi

log "[INFO] Cleaning local backups older than ${RETENTION_LOCAL_DAYS} days..."

LOCAL_DELETED="$(find "$BACKUP_DIR" \
  -type f \
  \( -name '3x-ui-backup_*.tar.gz' -o -name '3x-ui-backup_*.tar.gz.sha256' -o -name 'restore-info_*.txt' \) \
  -mtime +"$RETENTION_LOCAL_DAYS" \
  -print | wc -l)"

find "$BACKUP_DIR" \
  -type f \
  \( -name '3x-ui-backup_*.tar.gz' -o -name '3x-ui-backup_*.tar.gz.sha256' -o -name 'restore-info_*.txt' \) \
  -mtime +"$RETENTION_LOCAL_DAYS" \
  -delete

log "[OK] Backup completed: $ARCHIVE_PATH"
log "[INFO] Archive size:"
du -h "$ARCHIVE_PATH"

finish_report_once "OK"

log "========== 3x-ui backup v2 finished =========="
