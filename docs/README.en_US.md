**Language / Язык:** [Русский](../README.md) **|** <ins>English</ins>

# FrostbiteVPN — Telegram Bot for 3x-ui 3.4.x

Telegram bot for selling and managing VPN subscriptions via 3x-ui panel. Runs in Docker, connects to 3x-ui over internal network.

## Features

- User registration with trial period
- Subscription renewal via Telegram built-in payment system
- VLESS Reality profile creation in 3x-ui
- QR code generation for quick connection
- Automatic subscription expiration notifications
- Traffic usage statistics
- Admin menu (user management, broadcasts)
- Automatic subscription check every 3600s

## Quick Start (Docker)

### 1. Clone repositories

```bash
cd ~/.openclaw/workspace
git clone git@github.com:sqesh57-commits/frostbite-tg-client-bot.git
git clone git@github.com:sqesh57-commits/3x-ui-deploy-sq.git
```

Structure:
```
~/.openclaw/workspace/
├── 3x-ui-deploy-sq/          # 3x-ui panel
│   ├── compose.yml
│   └── ...
└── frostbite-tg-client-bot/  # Telegram bot
    ├── src/
    │   ├── .env              # Configuration (create from .env.example)
    │   └── .env.example
    ├── Dockerfile
    └── ...
```

### 2. Configure .env

```bash
cd frostbite-tg-client-bot
cp src/.env.example src/.env
```

Fill in required fields (see "Configuration" section below).

### 3. Build and run

```bash
cd ../3x-ui-deploy-sq
docker compose build frostbite-tg-client-bot
docker compose up -d frostbite-tg-client-bot
```

### 4. Verify

```bash
# Logs
docker logs -f frostbite-tg-client-bot

# API diagnostics
docker compose exec frostbite-tg-client-bot python check_xui.py
```

Expected `check_xui.py` output:
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

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Start and register |
| `/menu` | Main menu |
| `/renew` | Renew subscription |
| `/connect` | Connect to VPN (link + QR code) |
| `/stats` | Traffic statistics |
| `/help` | Help |

### Admin Functions

- Add/remove subscription time
- Delete user with profile cleanup in 3x-ui
- View user list
- Check and fix subscription discrepancies
- Network usage statistics
- Broadcast messages to users

## Configuration

File: `src/.env`

### Required Parameters

| Variable | Description | Example |
|----------|-------------|---------|
| `BOT_TOKEN` | Telegram bot token from @BotFather | `123456:ABC-DEF...` |
| `PAYMENT_TOKEN` | Payment token from @BotFather | `39054xxxx:LIVE:45xxx` |
| `ADMINS` | Telegram admin IDs, comma-separated; add the bot admin ID here to see `/orders` and the order review button | `1234567890,987654321` |
| `SUBSCRIPTION_PLANS` | Test tariffs for manual order review as JSON with `key`, `label`, `duration_days`, and `amount`; falls back to legacy `PRICES` when empty. | `'[{"key":"1w","label":"1 week","duration_days":7,"amount":100},{"key":"1m","label":"1 month","duration_days":30,"amount":270}]'` |
| `XUI_API_URL` | 3x-ui API URL (internal Docker) | `http://3x-ui-allinone:21443` |
| `XUI_USERNAME` | Panel login | `admin` |
| `XUI_PASSWORD` | Panel password | |
| `INBOUND_ID` | Reality inbound ID in 3x-ui | `3` |
| `XUI_HOST` | Public address for VLESS links | `vless.example.com` |

### Subscription Parameters

| Variable | Description | Default |
|----------|-------------|---------|
| `SUBSCRIPTION_URL_BASE` | Panel base URL | |
| `XUI_SUB_PATH` | Subscription path | `/sub/` |
| `XUI_SUB_PORT` | Subscription port | |

### Profile Creation Protection

| Variable | Description | Default |
|----------|-------------|---------|
| `BOT_REQUIRE_ADMIN_FOR_PROFILE_CREATE` | Enables additional business checks before self-service profile creation: active subscription/trial, no existing profile, blacklist, and rate limit. Regular users with active access are not blocked. | `false` |
| `BOT_BLOCKED_PROFILE_CREATE_IDS` | Comma-separated Telegram IDs that cannot create a new profile. | |
| `BOT_PROFILE_CREATE_RATE_LIMIT_SECONDS` | Minimum interval between profile creation attempts for one Telegram ID. | `60` |
| `BOT_MAX_PROFILES_PER_USER` | Maximum profiles per user; the current storage supports one profile, and `0` temporarily disables creation. | `1` |

Example for FrostbiteVPN:
```
SUBSCRIPTION_URL_BASE=https://panel.frostbite-rogueite22768.my-vm.work:20576
XUI_SUB_PATH=/frostbite-sub-8q2m7k/
```

Result: `https://panel...:20576/frostbite-sub-8q2m7k/<subId>`

### Reality Parameters (optional)

Usually auto-parsed from API. Used as fallback:

| Variable | Default |
|----------|---------|
| `REALITY_PUBLIC_KEY` | |
| `REALITY_SNI` | |
| `REALITY_SHORT_ID` | |
| `REALITY_FINGERPRINT` | `chrome` |
| `REALITY_SPIDER_X` | `/` |

### Security

| Variable | Description |
|----------|-------------|
| `XUI_VERIFY_SSL` | SSL verification (False for internal Docker) |
| `NGINX_BASIC_AUTH_USER` | BasicAuth user (not needed for internal URL) |
| `NGINX_BASIC_AUTH_PASSWORD` | BasicAuth password |
| `ADMIN_PANEL_PASSWORD` | Admin panel password |

## Architecture

```
Docker network
├── 3x-ui-allinone
│   ├── x-ui panel: 21443 (internal)
│   ├── nginx panel: 20576 (external)
│   ├── VLESS WS: 443
│   └── Reality: 30443
│
└── frostbite-tg-client-bot
    └── connects to http://3x-ui-allinone:21443
```

Bot connects to panel via internal Docker URL. No ports exposed externally.

### File Structure

```
frostbite-tg-client-bot/
├── src/
│   ├── app.py              # Entry point
│   ├── config.py           # Configuration (Pydantic)
│   ├── database.py         # SQLAlchemy models
│   ├── functions.py        # XUIAPI class + URL generation
│   ├── handlers.py         # Command handlers
│   ├── check_xui.py        # API diagnostics
│   └── .env.example        # Configuration template
├── templates/              # Jinja2 templates
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Diagnostics

### API Check

```bash
docker compose exec frostbite-tg-client-bot python check_xui.py
```

Checks:
- Login to 3x-ui
- Inbound retrieval
- Reality settings parsing
- Safe summary output (key masked)

### Telegram Check

```
/start
/connect
```

Verify in 3x-ui: new client should have `flow=xtls-rprx-vision`.

### VLESS URL Check

Link should contain:
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

## Rollback

If something goes wrong:

```bash
# Stop bot (safe — bot doesn't touch the panel)
docker compose stop frostbite-tg-client-bot

# Restore compose
cd ~/.openclaw/workspace/3x-ui-deploy-sq
git checkout compose.yml
docker compose up -d
```

Bot works ONLY through API. Stopping bot = zero changes to 3x-ui.

If panel DB is damaged:
```bash
cp data/x-ui/x-ui.db.bak_before_bot data/x-ui/x-ui.db
docker compose restart 3x-ui-allinone
```

## Security

- Secrets stored in `.env` (not committed)
- Reality keys parsed from API (not hardcoded)
- Bot doesn't read SQLite directly
- Container: `no-new-privileges`, resource limits
- Post-integration: recommend regenerating Reality keypair

## Pricing (defaults)

| Period | Price | Discount |
|--------|-------|----------|
| 1 month | 100 RUB | 0% |
| 3 months | 300 RUB | 10% |
| 6 months | 600 RUB | 20% |
| 12 months | 1200 RUB | 30% |

## Stack

- Python 3.12 + aiogram 3.x
- 3x-ui 3.4.x API
- SQLAlchemy + SQLite
- Docker + Docker Compose
- aiohttp (HTTP client)

## License

MIT
