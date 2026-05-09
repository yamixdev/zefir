import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    admins: list[int] = field(default_factory=list)
    database_url: str = os.getenv("DATABASE_URL", "")

    openweathermap_api_key: str = os.getenv("OPENWEATHERMAP_API_KEY", "")
    yandex_gpt_api_key: str = os.getenv("YANDEX_GPT_API_KEY", "")

    ai_daily_limit: int = int(os.getenv("AI_DAILY_LIMIT", "200"))
    ai_limit_hours: int = int(os.getenv("AI_LIMIT_HOURS", "12"))
    ai_history_limit: int = 30
    message_cooldown_sec: int = 3
    market_commission_percent: int = int(os.getenv("MARKET_COMMISSION_PERCENT", "25"))
    game_daily_win_limit: int = int(os.getenv("GAME_DAILY_WIN_LIMIT", "300"))
    ttt_turn_timeout_minutes: int = int(os.getenv("TTT_TURN_TIMEOUT_MINUTES", "15"))

    def __post_init__(self):
        raw = os.getenv("ADMINS", "")
        if raw:
            self.admins = [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admins


config = Config()
