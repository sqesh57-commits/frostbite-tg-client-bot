# Backup — FrostbiteVPN Bot

## Что бэкапится

| Файл/Папка | Описание |
|------------|----------|
| `src/` | Исходный код бота (Python) |
| `.env` | Конфигурация (токены, пароли) |
| `docker-compose.yml` | Docker compose конфиг |
| `Dockerfile` | Сборка контейнера |
| `requirements.txt` | Python зависимости |
| `backup/` | Скрипты и конфиги бэкапа |
| `api.txt` | Документация API 3x-ui |

**НЕ бэкапится:**
- `__pycache__/`, `*.pyc` — кэш Python
- `.git/` — git история
- `data/` —OLUME с БД (бэкапится отдельно через volume)
- `*.db` — файлы БД (находятся в Docker volume)
- `*.log` — логи

## Как запустить

```bash
cd ~/frostbite-tg-client-bot
bash backup/backup-bot.sh
```

## Куда бэкапится

| Назначение | Срок хранения |
|-----------|---------------|
| Локально (`~/backups/frostbite-bot/`) | 7 дней |
| Raspberry Pi | 30 дней |
| Google Drive | 90 дней |

## Как восстановить

```bash
cd ~/frostbite-tg-client-bot
docker compose down
tar -xzf ~/backups/frostbite-bot/frostbite-bot-backup_*.tar.gz
docker compose build && docker compose up -d
```

## Автозапуск (cron)

```bash
# Ежедневно в 3:00
crontab -e
0 3 * * * /home/sqesh/frostbite-tg-client-bot/backup/backup-bot.sh >> /home/sqesh/backups/frostbite-bot/cron.log 2>&1
```

## Telegram отчёт

После каждого бэкапа в Telegram приходит отчёт:
- Статус (OK/FAILED)
- Размер архива
- SHA256
- Статус загрузки на RPi и Google Drive
- Количество удалённых старых бэкапов

## Восстановление БД

БД (`users.db`) хранится в Docker volume и НЕ бэкапится скриптом.
Для бэкапа БД:

```bash
# Бэкап
docker exec frostbite-tg-client-bot sqlite3 /app/data/users.db .dump > ~/backups/frostbite-bot/users-db-backup.sql

# Восстановление
cat ~/backups/frostbite-bot/users-db-backup.sql | docker exec -i frostbite-tg-client-bot sqlite3 /app/data/users.db
```
