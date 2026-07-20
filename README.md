**Язык / Language:** <ins>Русский</ins> **|** [English](./docs/README.en_US.md)

# FrostbiteVPN — Telegram бот для 3x-ui 3.4.x

Telegram бот для продажи и управления VPN подписками через панель 3x-ui. Работает в Docker, подключается к 3x-ui по внутренней сети.

## Возможности

- Регистрация пользователей и пробный период
- Продление подписки через платежную систему Telegram
- Создание VLESS Reality профилей в 3x-ui
- Генерация QR-кодов для быстрого подключения
- Автоматические уведомления об истечении подписки
- Статистика использования трафика
- Административное меню (управление пользователями, рассылки)
- Автоматическая проверка подписок каждые 3600с

## Быстрый старт (Docker)

### 1. Клонировать репозитории

```bash
cd ~/.openclaw/workspace
git clone git@github.com:sqesh57-commits/frostbite-tg-client-bot.git
git clone git@github.com:sqesh57-commits/3x-ui-deploy-sq.git
```

Структура:
```
~/.openclaw/workspace/
├── 3x-ui-deploy-sq/          # Панель 3x-ui
│   ├── compose.yml
│   └── ...
└── frostbite-tg-client-bot/  # Telegram бот
    ├── src/
    │   ├── .env              # Конфигурация (создать из .env.example)
    │   └── .env.example
    ├── Dockerfile
    └── ...
```

### 2. Настроить .env

```bash
cd frostbite-tg-client-bot
cp src/.env.example src/.env
```

Заполнить обязательные поля (см. секцию "Конфигурация" ниже).

### 3. Собрать и запустить

```bash
cd ../3x-ui-deploy-sq
docker compose build frostbite-tg-client-bot
docker compose up -d frostbite-tg-client-bot
```

### 4. Проверить

```bash
# Логи
docker logs -f frostbite-tg-client-bot

# Диагностика API
docker compose exec frostbite-tg-client-bot python check_xui.py
```

Ожидаемый вывод `check_xui.py`:
```
login=True
inbound_exists=True
  id=3
  remark=VLESS\Reality
  port=30443
  protocol=vless
reality_loaded=True
  public_key=xxxxxxxx***
  sni=ya.ru
  sid=cb24***
  fp=chrome
  flow=xtls-rprx-vision
```

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Запуск и регистрация |
| `/menu` | Главное меню |
| `/renew` | Продление подписки |
| `/connect` | Подключение к VPN (ссылка + QR-код) |
| `/stats` | Статистика трафика |
| `/help` | Справка |

### Административные функции

- Добавление/удаление времени подписки
- Удаление пользователя с очисткой профиля в 3x-ui
- Просмотр списка пользователей
- Проверка и исправление расхождений подписок
- Статистика использования сети
- Рассылка сообщений пользователям

## Конфигурация

Файл: `src/.env`

### Обязательные параметры

| Переменная | Описание | Пример |
|-----------|----------|--------|
| `BOT_TOKEN` | Токен Telegram бота от @BotFather | `123456:ABC-DEF...` |
| `PAYMENT_TOKEN` | Платежный токен от @BotFather | `39054xxxx:LIVE:45xxx` |
| `ADMINS` | ID администраторов через запятую | `1234567890` |
| `XUI_API_URL` | URL API панели 3x-ui (внутренний Docker) | `http://3x-ui-allinone:21443` |
| `XUI_USERNAME` | Логин панели | `admin` |
| `XUI_PASSWORD` | Пароль панели | |
| `INBOUND_ID` | ID inbound с Reality в 3x-ui | `3` |
| `XUI_HOST` | Публичный адрес для VLESS ссылок | `vless.example.com` |
| `DB_PATH` | Путь к SQLite базе пользователей внутри контейнера | `/app/data/users.db` |

> `docker-compose.yml` монтирует `./data:/app/data`, поэтому значение `DB_PATH=/app/data/users.db` сохраняет базу на хосте в `./data/users.db`.

### Параметры подписки

| Переменная | Описание | По умолчанию |
|-----------|----------|-------------|
| `SUBSCRIPTION_URL_BASE` | Базовый URL панели | |
| `XUI_SUB_PATH` | Путь к подписке | `/sub/` |
| `XUI_SUB_PORT` | Порт подписки | |

Пример для FrostbiteVPN:
```
SUBSCRIPTION_URL_BASE=https://panel.frostbite-rogueite22768.my-vm.work:20576
XUI_SUB_PATH=/frostbite-sub-8q2m7k/
```

Результат: `https://panel...:20576/frostbite-sub-8q2m7k/<subId>`

### Reality параметры (опционально)

Обычно парсятся из API автоматически. Используют как fallback:

| Переменная | По умолчанию |
|-----------|-------------|
| `REALITY_PUBLIC_KEY` | |
| `REALITY_SNI` | |
| `REALITY_SHORT_ID` | |
| `REALITY_FINGERPRINT` | `chrome` |
| `REALITY_SPIDER_X` | `/` |

### Безопасность

| Переменная | Описание |
|-----------|----------|
| `XUI_VERIFY_SSL` | Проверка SSL (False для внутреннего Docker) |
| `NGINX_BASIC_AUTH_USER` | BasicAuth пользователь (не нужен для внутреннего URL) |
| `NGINX_BASIC_AUTH_PASSWORD` | BasicAuth пароль |
| `ADMIN_PANEL_PASSWORD` | Пароль админ-панели |

## Архитектура

```
Docker network
├── 3x-ui-allinone
│   ├── x-ui panel: 21443 (внутренний)
│   ├── nginx panel: 20576 (внешний)
│   ├── VLESS WS: 443
│   └── Reality: 30443
│
└── frostbite-tg-client-bot
    └── connects to http://3x-ui-allinone:21443
```

Бот подключается к панели через внутренний Docker URL. Наружу порты бота не публикуются.

### Файловая структура

```
frostbite-tg-client-bot/
├── src/
│   ├── app.py              # Точка входа
│   ├── config.py           # Конфигурация (Pydantic)
│   ├── database.py         # SQLAlchemy модели
│   ├── functions.py        # XUIAPI класс + генерация URL
│   ├── handlers.py         # Обработчики команд
│   ├── check_xui.py        # Диагностика API
│   └── .env.example        # Шаблон конфигурации
├── templates/              # Jinja2 шаблоны
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Диагностика

### Проверка API

```bash
docker compose exec frostbite-tg-client-bot python check_xui.py
```

Проверяет:
- Логин в 3x-ui
- Получение inbound
- Парсинг Reality settings
- Вывод safe summary (ключ замаскирован)

### Проверка из Telegram

```
/start
/connect
```

Проверить в 3x-ui: у нового клиента должен быть `flow=xtls-rprx-vision`.

### Проверка VLESS URL

Ссылка должна содержать:
```
vless://UUID@vless.example.com:30443
?type=tcp
&security=reality
&pbk=...
&fp=chrome
&sni=...
&sid=...
&spx=%2F
&flow=xtls-rprx-vision
&encryption=none
```

## Откат

Если что-то пошло не так:

```bash
# Остановить бота (безопасно — бот не трогает панель)
docker compose stop frostbite-tg-client-bot

# Восстановить compose
cd ~/.openclaw/workspace/3x-ui-deploy-sq
git checkout compose.yml
docker compose up -d
```

Бот работает ТОЛЬКО через API. Остановка бота = ноль изменений в 3x-ui.

Если повреждена БД панели:
```bash
cp data/x-ui/x-ui.db.bak_before_bot data/x-ui/x-ui.db
docker compose restart 3x-ui-allinone
```

## Безопасность

- Секреты хранятся в `.env` (не коммитятся)
- Reality ключи парсятся из API (не хардкодятся)
- Бот не читает SQLite напрямую
- Контейнер: `no-new-privileges`, ограниченные ресурсы
- После интеграции: рекомендуется пересоздать Reality keypair

## Цены (по умолчанию)

| Период | Цена | Скидка |
|--------|------|--------|
| 1 месяц | 100 руб. | 0% |
| 3 месяца | 300 руб. | 10% |
| 6 месяцев | 600 руб. | 20% |
| 12 месяцев | 1200 руб. | 30% |

## Стек

- Python 3.12 + aiogram 3.x
- 3x-ui 3.4.x API
- SQLAlchemy + SQLite
- Docker + Docker Compose
- aiohttp (HTTP клиент)

## Лицензия

MIT
