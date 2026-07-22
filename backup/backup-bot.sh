#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/backup-bot.env"

[ -f "$ENV_FILE" ] || {
  echo "[ERROR] Config not found: $ENV_FILE"
  exit 1
}

# shellcheck source=/dev/null
source "$ENV_FILE"

DATE="$(date +'%Y-%m-%d_%H-%M-%S')"
ARCHIVE_NAME="frostbite-bot-backup_${DATE}.tar.gz"
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
ARCHIVE_STATUS="UNKNOWN"
SHA256_STATUS="UNKNOWN"
START_TS="$(date +%s)"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

exec >> "$LOG_FILE" 2>&1

log() {
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

send_telegram() {
  local text="$1"
  if [ "${ENABLE_TELEGRAM:-false}" != "true" ]; then return 0; fi
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
  local end_ts duration size sha_short result_icon result_line
  end_ts="$(date +%s)"
  duration="$((end_ts - START_TS)) sec"

  if [ "$result" = "OK" ]; then
    result_icon="✅"
    result_line="Backup выполнен успешно"
  else
    result_icon="🔴"
    result_line="Backup FAILED"
  fi

  [ -f "$ARCHIVE_PATH" ] && size="$(du -h "$ARCHIVE_PATH" | awk '{print $1}')" || size="n/a"
  [ -f "$SHA256_PATH" ] && sha_short="$(cut -d ' ' -f1 "$SHA256_PATH" | cut -c1-12)" || sha_short="n/a"

  local report
  report="$(cat <<EOF
🦞 <b>FrostbiteVPN Bot Backup</b>

${result_icon} <b>${result_line}</b>

🖥 <b>Host</b>
$(hostname)

📦 <b>Archive</b>
${ARCHIVE_NAME}

📏 <b>Size</b>
${size}

🔐 <b>SHA256</b>
${sha_short}...

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
  [ "$FINAL_REPORT_SENT" = "true" ] && return 0
  FINAL_REPORT_SENT="true"
  finish_report "$1"
}

cleanup() {
  local exit_code=$?
  [ "$exit_code" -ne 0 ] && finish_report_once "FAILED"
  exit "$exit_code"
}

fail() { log "[ERROR] $*"; exit 1; }
trap cleanup EXIT

check_command() { command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"; }

log "========== frostbite-bot backup started =========="

check_command tar
check_command sha256sum
check_command curl
[ "${ENABLE_RPI_UPLOAD:-false}" = "true" ] && { check_command rsync; check_command ssh; }
[ "${ENABLE_GDRIVE_UPLOAD:-false}" = "true" ] && check_command rclone

[ -d "$PROJECT_DIR" ] || fail "Project dir not found: $PROJECT_DIR"
cd "$PROJECT_DIR"

[ -f "docker-compose.yml" ] || [ -f "compose.yml" ] || fail "docker-compose.yml not found"
[ -f ".env" ] || fail ".env not found (create from src/.env.example)"

log "[INFO] Creating restore info..."
cat > "$RESTORE_INFO_PATH" <<EOF
Backup date: ${DATE}
Host: $(hostname)
Project dir: ${PROJECT_DIR}
Container: ${CONTAINER_NAME}
Archive: ${ARCHIVE_NAME}
Created by: backup-bot.sh

Restore:
  cd ${PROJECT_DIR}
  docker compose down
  tar -xzf ${ARCHIVE_NAME}
  docker compose build && docker compose up -d

Check:
  docker ps
  docker logs --tail=100 ${CONTAINER_NAME}
EOF

log "[INFO] Creating archive: $ARCHIVE_PATH"

tar \
  --exclude='__pycache__' \
  --exclude='.git' \
  --exclude='*.pyc' \
  --exclude='data/' \
  --exclude='*.db' \
  --exclude='.mimocode' \
  --exclude='*.log' \
  --exclude='*.tmp' \
  -czf "$ARCHIVE_PATH" \
  src/ \
  Dockerfile \
  docker-compose.yml \
  requirements.txt \
  .env \
  .env.bot.example \
  .dockerignore \
  backup/ \
  reset_db.sh \
  3X-UI\ Panel\ API.postman_collection.json \
  api.txt \
  -C "$BACKUP_DIR" "$RESTORE_INFO" \
  2>/tmp/bot-backup-tar-error.log

[ "$?" -ne 0 ] && { cat /tmp/bot-backup-tar-error.log; fail "tar archive creation failed"; }

chmod 600 "$ARCHIVE_PATH"
tar -tzf "$ARCHIVE_PATH" >/dev/null || fail "Archive verification failed"

ARCHIVE_SIZE_BYTES="$(stat -c%s "$ARCHIVE_PATH")"
[ "$ARCHIVE_SIZE_BYTES" -lt 1024 ] && fail "Archive too small: ${ARCHIVE_SIZE_BYTES} bytes"

ARCHIVE_STATUS="OK"
LOCAL_STATUS="OK"
log "[OK] Archive verified ($(du -h "$ARCHIVE_PATH" | awk '{print $1}'))"

log "[INFO] Creating sha256..."
sha256sum "$ARCHIVE_PATH" > "$SHA256_PATH"
chmod 600 "$SHA256_PATH"
SHA256_STATUS="OK"

# RPi upload
if [ "${ENABLE_RPI_UPLOAD:-false}" = "true" ]; then
  log "[INFO] Uploading to Raspberry Pi..."
  if timeout 30 ssh -i "$RPI_IDENTITY_FILE" -p "$RPI_PORT" -o BatchMode=yes -o ConnectTimeout=10 \
    "${RPI_USER}@${RPI_HOST}" "mkdir -p '$RPI_TARGET_DIR' && test -w '$RPI_TARGET_DIR'" 2>/dev/null; then

    if timeout 300 rsync -avz \
      -e "ssh -i $RPI_IDENTITY_FILE -p $RPI_PORT -o BatchMode=yes -o ConnectTimeout=10" \
      "$ARCHIVE_PATH" "$SHA256_PATH" \
      "${RPI_USER}@${RPI_HOST}:${RPI_TARGET_DIR}/" 2>/dev/null; then

      if timeout 30 ssh -i "$RPI_IDENTITY_FILE" -p "$RPI_PORT" -o BatchMode=yes \
        "${RPI_USER}@${RPI_HOST}" \
        "test -f '${RPI_TARGET_DIR}/${ARCHIVE_NAME}'" 2>/dev/null; then
        RPI_STATUS="OK"
        log "[OK] RPi upload verified"
      else
        RPI_STATUS="FAIL_VERIFY"
      fi

      # Cleanup old RPi backups
      RPI_DELETED="$(timeout 30 ssh -i "$RPI_IDENTITY_FILE" -p "$RPI_PORT" -o BatchMode=yes \
        "${RPI_USER}@${RPI_HOST}" \
        "find '$RPI_TARGET_DIR' -type f -name 'frostbite-bot-backup_*' -mtime +${RETENTION_RPI_DAYS} -print 2>/dev/null | wc -l" || echo 0)"
      timeout 30 ssh -i "$RPI_IDENTITY_FILE" -p "$RPI_PORT" -o BatchMode=yes \
        "${RPI_USER}@${RPI_HOST}" \
        "find '$RPI_TARGET_DIR' -type f -name 'frostbite-bot-backup_*' -mtime +${RETENTION_RPI_DAYS} -delete" || true
    else
      RPI_STATUS="FAIL_UPLOAD"
    fi
  else
    RPI_STATUS="FAIL_CONNECT"
  fi
fi

# Google Drive upload
if [ "${ENABLE_GDRIVE_UPLOAD:-false}" = "true" ]; then
  log "[INFO] Uploading to Google Drive..."
  if timeout 600 rclone copy "$ARCHIVE_PATH" "${GDRIVE_REMOTE}:${GDRIVE_PATH}/" \
    && timeout 600 rclone copy "$SHA256_PATH" "${GDRIVE_REMOTE}:${GDRIVE_PATH}/"; then
    if rclone lsf "${GDRIVE_REMOTE}:${GDRIVE_PATH}/" --files-only 2>/dev/null | grep -Fxq "$ARCHIVE_NAME"; then
      GDRIVE_STATUS="OK"
      log "[OK] Google Drive upload verified"
    else
      GDRIVE_STATUS="FAIL_VERIFY"
    fi
    GDRIVE_DELETED="$(rclone lsf "${GDRIVE_REMOTE}:${GDRIVE_PATH}/" --files-only --min-age "${RETENTION_GDRIVE_DAYS}d" --include "frostbite-bot-backup_*" 2>/dev/null | wc -l)"
    rclone delete --min-age "${RETENTION_GDRIVE_DAYS}d" --include "frostbite-bot-backup_*" "${GDRIVE_REMOTE}:${GDRIVE_PATH}/" || true
  else
    GDRIVE_STATUS="FAIL_UPLOAD"
  fi
fi

# Local retention
log "[INFO] Cleaning local backups older than ${RETENTION_LOCAL_DAYS} days..."
LOCAL_DELETED="$(find "$BACKUP_DIR" -type f -name 'frostbite-bot-backup_*' -mtime +"$RETENTION_LOCAL_DAYS" -print 2>/dev/null | wc -l)"
find "$BACKUP_DIR" -type f -name 'frostbite-bot-backup_*' -mtime +"$RETENTION_LOCAL_DAYS" -delete 2>/dev/null || true

log "[OK] Backup completed: $ARCHIVE_PATH ($(du -h "$ARCHIVE_PATH" | awk '{print $1}'))"

finish_report_once "OK"
log "========== frostbite-bot backup finished =========="
