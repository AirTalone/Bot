from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = ""
    admin_ids: str = ""
    database_url: str = "sqlite+aiosqlite:///data/bot.db"
    payment_title: str = "Оплата VPN"
    payment_details: str = "Укажите реквизиты в PAYMENT_DETAILS"
    payment_qr_payload: str = ""
    support_contact: str = ""
    auto_create_sqlite: bool = True

    panel_enabled: bool = False
    panel_provider: str = "marzban"
    panel_base_url: str = ""
    panel_username: str = ""
    panel_password: str = ""
    panel_proxies_json: str = '{"vless": {}}'
    panel_inbounds_json: str = "{}"

    order_cooldown_seconds: int = 30
    paid_cooldown_seconds: int = 20
    reminder_days_before: int = 3
    reminder_interval_seconds: int = 3600

    @field_validator(
        "admin_ids",
        "payment_title",
        "payment_details",
        "payment_qr_payload",
        "support_contact",
        "bot_token",
        "database_url",
        "panel_provider",
        "panel_base_url",
        "panel_username",
        "panel_password",
        "panel_proxies_json",
        "panel_inbounds_json",
    )
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @property
    def admin_id_list(self) -> list[int]:
        if not self.admin_ids:
            return []
        return [int(part.strip()) for part in self.admin_ids.split(",") if part.strip()]

    def require_bot_token(self) -> str:
        if not self.bot_token:
            raise RuntimeError("BOT_TOKEN is required")
        return self.bot_token


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

