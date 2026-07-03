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
    XUI_SUB_PORT: str = os.getenv("XUI_SUB_PORT", "54321")
    XUI_API_TOKEN: str = os.getenv("XUI_API_TOKEN", "")
    XUI_USERNAME: str = os.getenv("XUI_USERNAME", "admin")
    XUI_PASSWORD: str = os.getenv("XUI_PASSWORD", "admin")
    XUI_HOST: str = os.getenv("XUI_HOST", "your-server.com")
    XUI_SERVER_NAME: str = os.getenv("XUI_SERVER_NAME", "domain.com")
    XUI_VERIFY_SSL: bool = Field(default=os.getenv("XUI_VERIFY_SSL", "True").lower() == "true")
    PAYMENT_TOKEN: str = os.getenv("PAYMENT_TOKEN", "")
    INBOUND_ID: int = Field(default=os.getenv("INBOUND_ID", 1))
    SUBSCRIPTION_URL_BASE: str = os.getenv("SUBSCRIPTION_URL_BASE", "")
    REALITY_FINGERPRINT: str = os.getenv("REALITY_FINGERPRINT", "chrome")
    REALITY_SPIDER_X: str = os.getenv("REALITY_SPIDER_X", "/")
    NGINX_BASIC_AUTH_USER: str = os.getenv("NGINX_BASIC_AUTH_USER", "")
    NGINX_BASIC_AUTH_PASSWORD: str = os.getenv("NGINX_BASIC_AUTH_PASSWORD", "")
    # Reality настройки подтягиваются из inbound автоматически
    REALITY_PUBLIC_KEY: str = ""
    REALITY_SNI: str = ""
    REALITY_SHORT_ID: str = ""

    PRICES: Dict[int, Dict[str, int]] = {
        1: {"base_price": 100, "discount_percent": 0},
        3: {"base_price": 300, "discount_percent": 10},
        6: {"base_price": 600, "discount_percent": 20},
        12: {"base_price": 1200, "discount_percent": 30}
    }

    @field_validator('ADMINS', mode='before')
    def parse_admins(cls, value):
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
    INBOUND_ID=os.getenv("INBOUND_ID", 1)
)
