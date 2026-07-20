import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from typing import List, Dict

load_dotenv()


class Config(BaseModel):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMINS: List[int] = Field(default_factory=list)
    XUI_API_URL: str = os.getenv("XUI_API_URL", "http://localhost:54321")
    XUI_BASE_PATH: str = os.getenv("XUI_BASE_PATH", "/panel")
    XUI_SUB_PATH: str = os.getenv("XUI_SUB_PATH", "/sub/")
    XUI_SUB_PORT: str = os.getenv("XUI_SUB_PORT", "")
    XUI_API_TOKEN: str = os.getenv("XUI_API_TOKEN", "")
    XUI_USERNAME: str = os.getenv("XUI_USERNAME", "admin")
    XUI_PASSWORD: str = os.getenv("XUI_PASSWORD", "admin")
    XUI_HOST: str = os.getenv("XUI_HOST", "your-server.com")
    XUI_SERVER_NAME: str = os.getenv("XUI_SERVER_NAME", "domain.com")
    XUI_VERIFY_SSL: bool = Field(default=os.getenv("XUI_VERIFY_SSL", "True").lower() == "true")
    PAYMENT_TOKEN: str = os.getenv("PAYMENT_TOKEN", "")
    INBOUND_ID: int = Field(default=os.getenv("INBOUND_ID", 1))
    SUBSCRIPTION_URL_BASE: str = os.getenv("SUBSCRIPTION_URL_BASE", "")
    REALITY_PUBLIC_KEY: str = os.getenv("REALITY_PUBLIC_KEY", "")
    REALITY_SNI: str = os.getenv("REALITY_SNI", "")
    REALITY_SHORT_ID: str = os.getenv("REALITY_SHORT_ID", "")
    REALITY_FINGERPRINT: str = os.getenv("REALITY_FINGERPRINT", "chrome")
    REALITY_SPIDER_X: str = os.getenv("REALITY_SPIDER_X", "/")
    NGINX_BASIC_AUTH_USER: str = os.getenv("NGINX_BASIC_AUTH_USER", "")
    NGINX_BASIC_AUTH_PASSWORD: str = os.getenv("NGINX_BASIC_AUTH_PASSWORD", "")
    ADMIN_PANEL_PASSWORD: str = os.getenv("ADMIN_PANEL_PASSWORD", "")
    ENABLE_CODE_EDITOR: bool = Field(default=os.getenv("ENABLE_CODE_EDITOR", "false").lower() == "true")

    # Safety flags
    XUI_ALLOW_FULL_INBOUND_UPDATE: bool = Field(
        default=os.getenv("XUI_ALLOW_FULL_INBOUND_UPDATE", "false").lower() == "true"
    )
    BOT_DRY_RUN: bool = Field(default=os.getenv("BOT_DRY_RUN", "false").lower() == "true")
    BOT_REQUIRE_ADMIN_FOR_PROFILE_CREATE: bool = Field(
        default=os.getenv("BOT_REQUIRE_ADMIN_FOR_PROFILE_CREATE", "false").lower() == "true"
    )
    BOT_BLOCKED_PROFILE_CREATE_IDS: List[int] = Field(default_factory=list)
    BOT_PROFILE_CREATE_RATE_LIMIT_SECONDS: int = Field(
        default=int(os.getenv("BOT_PROFILE_CREATE_RATE_LIMIT_SECONDS", "60"))
    )
    BOT_MAX_PROFILES_PER_USER: int = Field(default=int(os.getenv("BOT_MAX_PROFILES_PER_USER", "1")))
    TRIAL_DAYS: int = Field(default=int(os.getenv("TRIAL_DAYS", "3")))

    PRICES: Dict[int, Dict[str, int]] = {
        1: {"base_price": 100, "discount_percent": 0},
        3: {"base_price": 300, "discount_percent": 10},
        6: {"base_price": 600, "discount_percent": 20},
        12: {"base_price": 1200, "discount_percent": 30}
    }

    @field_validator('ADMINS', 'BOT_BLOCKED_PROFILE_CREATE_IDS', mode='before')
    def parse_id_list(cls, value):
        if isinstance(value, str):
            return [int(admin) for admin in value.split(",") if admin.strip()]
        return value or []

    @field_validator('INBOUND_ID', mode='before')
    def parse_inbound_id(cls, value):
        if isinstance(value, str):
            return int(value)
        return value or 1

    def calculate_price(self, months: int) -> int:
        if months not in self.PRICES:
            return 0
        price_info = self.PRICES[months]
        base_price = price_info["base_price"]
        discount_percent = price_info["discount_percent"]
        discount_amount = (base_price * discount_percent) // 100
        return base_price - discount_amount


config = Config(
    ADMINS=os.getenv("ADMINS", ""),
    BOT_BLOCKED_PROFILE_CREATE_IDS=os.getenv("BOT_BLOCKED_PROFILE_CREATE_IDS", ""),
    INBOUND_ID=os.getenv("INBOUND_ID", 1)
)
