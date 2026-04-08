import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    admins: list[int] = field(default_factory=list)
    database_url: str = os.getenv("DATABASE_URL", "")

    # OpenWeatherMap
    openweathermap_api_key: str = os.getenv("OPENWEATHERMAP_API_KEY", "")

    # Yandex GPT
    yandex_gpt_api_key: str = os.getenv("YANDEX_GPT_API_KEY", "")
    yandex_gpt_base_url: str = os.getenv("YANDEX_GPT_BASE_URL", "https://ai.api.cloud.yandex.net/v1")
    yandex_gpt_project: str = os.getenv("YANDEX_GPT_PROJECT", "")
    yandex_gpt_prompt_id: str = os.getenv("YANDEX_GPT_PROMPT_ID", "")

    # Rate limits
    ai_daily_limit: int = int(os.getenv("AI_DAILY_LIMIT", "52"))
    ai_limit_hours: int = int(os.getenv("AI_LIMIT_HOURS", "12"))
    message_cooldown_sec: int = 3

    def __post_init__(self):
        raw = os.getenv("ADMINS", "")
        if raw:
            self.admins = [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admins


config = Config()
