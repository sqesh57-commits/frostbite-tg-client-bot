import aiohttp
import uuid
import json
import logging
import random
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, quote, urlparse
from config import config

logger = logging.getLogger(__name__)


class XUIAPI:
    def __init__(self):
        self.session = None
        self.cookie_jar = aiohttp.CookieJar(unsafe=True)
        self._reality_cache = None

    def _loads_json(self, value, default=None):
        if default is None:
            default = {}
        if isinstance(value, (dict, list)):
            return value
        if not value:
            return default
        try:
            return json.loads(value)
        except Exception:
            return default

    def _first(self, value, default=""):
        if isinstance(value, list):
            return value[0] if value else default
        return value or default

    async def _ensure_session(self):
        if self.session is None:
            connector = aiohttp.TCPConnector(ssl=config.XUI_VERIFY_SSL)
            self.session = aiohttp.ClientSession(
                connector=connector,
                cookie_jar=self.cookie_jar,
                trust_env=True
            )

    def _build_url(self, path: str) -> str:
        base_url = config.XUI_API_URL.rstrip('/')
        return f"{base_url}{path}"

    def _auth_headers(self) -> dict:
        headers = {}
        url = config.XUI_API_URL.lower()
        if "localhost" in url or "127.0.0.1" in url:
            # Localhost — nginx пропускает, шлём Bearer токен панели
            if config.XUI_API_TOKEN:
                headers["Authorization"] = f"Bearer {config.XUI_API_TOKEN}"
        else:
            # Внешний доступ — нужен Basic auth для nginx
            if config.NGINX_BASIC_AUTH_USER:
                import base64
                creds = base64.b64encode(
                    f"{config.NGINX_BASIC_AUTH_USER}:{config.NGINX_BASIC_AUTH_PASSWORD}".encode()
                ).decode()
                headers["Authorization"] = f"Basic {creds}"
        return headers

    async def login(self):
        try:
            await self._ensure_session()
            login_url = self._build_url("/login")

            async with self.session.post(
                login_url,
                data={"username": config.XUI_USERNAME, "password": config.XUI_PASSWORD},
                headers=self._auth_headers()
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Login failed with status: {resp.status}")
                    return False

                try:
                    response = await resp.json()
                    if response.get("success"):
                        logger.info("Login successful")
                        return True
                    else:
                        logger.error(f"Login failed: {response.get('msg')}")
                        return False
                except Exception:
                    text = await resp.text()
                    if "success" in text.lower():
                        return True
                    return False
        except Exception as e:
            logger.exception(f"Login error: {e}")
            return False

    async def get_inbound(self, inbound_id: int):
        try:
            await self._ensure_session()
            url = self._build_url(f"/api/inbounds/get/{inbound_id}")

            async with self.session.get(url, headers=self._auth_headers()) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if data.get("success"):
                    return data.get("obj")
                return None
        except Exception as e:
            logger.exception(f"Get inbound error: {e}")
            return None

    async def update_inbound(self, inbound_id: int, data: dict):
        try:
            await self._ensure_session()
            url = self._build_url(f"/api/inbounds/update/{inbound_id}")

            async with self.session.post(url, json=data, headers=self._auth_headers()) as resp:
                if resp.status != 200:
                    return False
                response = await resp.json()
                return response.get("success", False)
        except Exception as e:
            logger.exception(f"Update inbound error: {e}")
            return False

    async def get_reality_settings(self) -> dict:
        if self._reality_cache:
            return self._reality_cache

        inbound = await self.get_inbound(config.INBOUND_ID)
        if not inbound:
            logger.error("Failed to get inbound for Reality settings")
            return {}

        try:
            stream_settings_raw = (
                inbound.get("streamSettings")
                or inbound.get("stream_settings")
                or "{}"
            )
            inbound_settings_raw = inbound.get("settings") or "{}"

            stream_settings = self._loads_json(stream_settings_raw, {})
            inbound_settings = self._loads_json(inbound_settings_raw, {})

            reality = stream_settings.get("realitySettings", {})
            reality_nested = reality.get("settings", {})

            clients = inbound_settings.get("clients", [])
            first_client_flow = ""
            if clients:
                first_client_flow = next(
                    (c.get("flow", "") for c in clients if c.get("flow")),
                    ""
                )

            public_key = (
                reality_nested.get("publicKey")
                or reality.get("publicKey")
                or config.REALITY_PUBLIC_KEY
                or ""
            )

            sni = (
                reality_nested.get("serverName")
                or self._first(reality.get("serverNames"), "")
                or self._first(reality_nested.get("serverNames"), "")
                or config.REALITY_SNI
                or config.XUI_SERVER_NAME
                or ""
            )

            short_id = (
                self._first(reality.get("shortIds"), "")
                or reality_nested.get("shortId")
                or self._first(reality_nested.get("shortIds"), "")
                or config.REALITY_SHORT_ID
                or ""
            )

            spider_x = (
                reality_nested.get("spiderX")
                or reality.get("spiderX")
                or config.REALITY_SPIDER_X
                or "/"
            )

            fingerprint = (
                reality_nested.get("fingerprint")
                or reality.get("fingerprint")
                or config.REALITY_FINGERPRINT
                or "chrome"
            )

            flow = (
                first_client_flow
                or reality_nested.get("flow")
                or reality.get("flow")
                or "xtls-rprx-vision"
            )

            port = inbound.get("port", 443)

            missing = []
            if not public_key:
                missing.append("public_key")
            if not sni:
                missing.append("sni")
            if not short_id:
                missing.append("short_id")

            if missing:
                logger.error(f"Reality settings incomplete. Missing: {', '.join(missing)}")
                return {}

            self._reality_cache = {
                "public_key": public_key,
                "sni": sni,
                "short_id": short_id,
                "spider_x": spider_x,
                "fingerprint": fingerprint,
                "flow": flow,
                "port": port,
            }

            logger.info(
                f"Reality settings loaded: sni={sni}, sid={short_id}, "
                f"fp={fingerprint}, spx={spider_x}, flow={flow}, port={port}"
            )
            return self._reality_cache

        except Exception as e:
            logger.exception(f"Failed to parse Reality settings: {e}")
            return {}

    async def create_vless_profile(self, telegram_id: int, expiry_time: int = 0):
        if not await self.login():
            return None

        if expiry_time < 0:
            expiry_time = 0

        inbound = await self.get_inbound(config.INBOUND_ID)
        if not inbound:
            return None

        reality = await self.get_reality_settings()
        if not reality:
            logger.error("Cannot create profile: Reality settings not available")
            return None

        try:
            settings = json.loads(inbound["settings"])
            clients = settings.get("clients", [])

            client_id = str(uuid.uuid4())
            email = f"user_{telegram_id}_{random.randint(1000, 9999)}"
            sub_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"user_{telegram_id}"))

            new_client = {
                "id": client_id,
                "flow": reality.get("flow", "xtls-rprx-vision"),
                "email": email,
                "limitIp": 0,
                "totalGB": 0,
                "expiryTime": expiry_time * 1000,
                "enable": True,
                "tgId": "",
                "subId": sub_id,
                "reset": 0,
            }

            if expiry_time < 1577836800:
                new_client["expiryTime"] = 0
            elif expiry_time > 2000000000:
                new_client["expiryTime"] = 0

            clients.append(new_client)
            settings["clients"] = clients

            update_data = {
                "up": inbound["up"],
                "down": inbound["down"],
                "total": inbound["total"],
                "remark": inbound["remark"],
                "enable": inbound["enable"],
                "expiryTime": inbound["expiryTime"],
                "listen": inbound["listen"],
                "port": inbound["port"],
                "protocol": inbound["protocol"],
                "settings": json.dumps(settings, indent=2),
                "streamSettings": inbound["streamSettings"],
                "sniffing": inbound["sniffing"],
            }

            if await self.update_inbound(config.INBOUND_ID, update_data):
                return {
                    "client_id": client_id,
                    "email": email,
                    "port": reality.get("port", inbound.get("port", 443)),
                    "security": "reality",
                    "remark": inbound["remark"],
                    "sni": reality["sni"],
                    "pbk": reality["public_key"],
                    "fp": reality.get("fingerprint", config.REALITY_FINGERPRINT),
                    "sid": reality["short_id"],
                    "spx": reality.get("spider_x", config.REALITY_SPIDER_X),
                    "flow": reality.get("flow", "xtls-rprx-vision"),
                    "sub_id": sub_id,
                }
            return None
        except Exception as e:
            logger.exception(f"Create profile error: {e}")
            return None

    async def update_client_expiry(self, email: str, expiry_time: int):
        if not await self.login():
            return False

        if expiry_time < 0:
            expiry_time = 0

        try:
            inbound = await self.get_inbound(config.INBOUND_ID)
            if not inbound:
                return False

            settings = json.loads(inbound["settings"])
            clients = settings.get("clients", [])

            updated = False
            for client in clients:
                if client["email"] == email:
                    final_expiry_time = expiry_time
                    if expiry_time < 1577836800:
                        final_expiry_time = 0
                    elif expiry_time > 2000000000:
                        final_expiry_time = 0
                    client["expiryTime"] = final_expiry_time * 1000
                    updated = True
                    break

            if not updated:
                return False

            settings["clients"] = clients

            update_data = {
                "up": inbound["up"],
                "down": inbound["down"],
                "total": inbound["total"],
                "remark": inbound["remark"],
                "enable": inbound["enable"],
                "expiryTime": inbound["expiryTime"],
                "listen": inbound["listen"],
                "port": inbound["port"],
                "protocol": inbound["protocol"],
                "settings": json.dumps(settings, indent=2),
                "streamSettings": inbound["streamSettings"],
                "sniffing": inbound["sniffing"],
            }

            return await self.update_inbound(config.INBOUND_ID, update_data)
        except Exception as e:
            logger.exception(f"Update client expiry error: {e}")
            return False

    async def get_user_stats(self, email: str):
        if not await self.login():
            return {"upload": 0, "download": 0}

        try:
            url = self._build_url(f"/api/inbounds/getClientTraffics/{email}")

            async with self.session.get(url, headers=self._auth_headers()) as resp:
                if resp.status != 200:
                    return {"upload": 0, "download": 0}

                data = await resp.json()
                if data.get("success"):
                    client_data = data.get("obj")
                    if isinstance(client_data, dict):
                        return {
                            "upload": client_data.get("up", 0),
                            "download": client_data.get("down", 0)
                        }
        except Exception as e:
            logger.error(f"Stats error: {e}")
        return {"upload": 0, "download": 0}

    async def get_online_users(self):
        if not await self.login():
            return 0

        try:
            url = self._build_url("/api/inbounds/onlines")

            async with self.session.post(url, headers=self._auth_headers()) as resp:
                if resp.status != 200:
                    return 0

                data = await resp.json()
                online = 0
                if data.get("success"):
                    users = data.get("obj")
                    if isinstance(users, list):
                        for user in users:
                            if str(user).startswith("user_"):
                                online += 1
                return online
        except Exception as e:
            logger.error(f"Online users error: {e}")
        return 0

    async def close(self):
        if self.session:
            await self.session.close()


# === Wrapper functions ===

async def create_vless_profile(telegram_id: int, expiry_time: int = 0):
    api = XUIAPI()
    try:
        return await api.create_vless_profile(telegram_id, expiry_time)
    finally:
        await api.close()


async def update_client_expiry(email: str, expiry_time: int):
    api = XUIAPI()
    try:
        return await api.update_client_expiry(email, expiry_time)
    finally:
        await api.close()


async def get_online_users():
    api = XUIAPI()
    try:
        return await api.get_online_users()
    finally:
        await api.close()


async def get_user_stats(email: str):
    api = XUIAPI()
    try:
        return await api.get_user_stats(email)
    finally:
        await api.close()


def generate_sub_url(sub_id: str) -> str:
    sub_path = (config.XUI_SUB_PATH or "/sub/").strip()

    if not sub_path.startswith("/"):
        sub_path = f"/{sub_path}"
    if not sub_path.endswith("/"):
        sub_path = f"{sub_path}/"

    if not config.SUBSCRIPTION_URL_BASE:
        parsed = urlparse(config.XUI_API_URL)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or "localhost"
        port = f":{config.XUI_SUB_PORT}" if config.XUI_SUB_PORT else ""
        return f"{scheme}://{host}{port}{sub_path}{sub_id}"

    return f"{config.SUBSCRIPTION_URL_BASE.rstrip('/')}{sub_path}{sub_id}"


def generate_vless_url(profile_data: dict) -> str:
    remark = profile_data.get("remark", "")
    email = profile_data["email"]
    fragment = f"{remark}-{email}" if remark else email

    query = {
        "type": "tcp",
        "security": "reality",
        "pbk": profile_data.get("pbk", ""),
        "fp": profile_data.get("fp", "chrome"),
        "sni": profile_data.get("sni", ""),
        "sid": profile_data.get("sid", ""),
        "spx": profile_data.get("spx", "/"),
        "flow": profile_data.get("flow", "xtls-rprx-vision"),
        "encryption": "none",
    }

    return (
        f"vless://{profile_data['client_id']}@{config.XUI_HOST}:{profile_data['port']}"
        f"?{urlencode(query)}"
        f"#{quote(fragment)}"
    )


def get_safe_expiry_timestamp(subscription_end) -> int:
    if subscription_end is None:
        return 0

    if isinstance(subscription_end, str):
        try:
            subscription_end = datetime.fromisoformat(subscription_end)
        except Exception:
            return 0

    if not isinstance(subscription_end, datetime):
        return 0

    # Strip timezone for comparison (SQLite stores naive datetimes)
    sub = subscription_end.replace(tzinfo=None)
    now = datetime.utcnow()

    if sub < datetime(2020, 1, 1):
        return 0

    if sub > now + timedelta(days=3650):
        return 0

    if sub <= now:
        return 0

    try:
        timestamp = int(sub.timestamp())
        if timestamp < 0 or timestamp < 1577836800:
            return 0
        return timestamp
    except Exception:
        return 0


async def force_update_profile_expiry(email: str, subscription_end) -> bool:
    try:
        expiry_time = get_safe_expiry_timestamp(subscription_end)
        return await update_client_expiry(email, expiry_time)
    except Exception as e:
        logger.error(f"Error force updating profile {email}: {e}")
        return False
