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
    app_timezone: str = os.getenv("APP_TIMEZONE", "Europe/Moscow")
    shop_rotation_hours: int = int(os.getenv("SHOP_ROTATION_HOURS", "12"))
    ttt_turn_timeout_minutes: int = int(os.getenv("TTT_TURN_TIMEOUT_MINUTES", "15"))
    game_session_timeout_minutes: int = int(os.getenv("GAME_SESSION_TIMEOUT_MINUTES", "30"))
    stale_game_timeout_minutes: int = int(os.getenv("STALE_GAME_TIMEOUT_MINUTES", "5"))
    ranked_season_days: int = int(os.getenv("RANKED_SEASON_DAYS", "14"))
    ranked_start_elo: int = int(os.getenv("RANKED_START_ELO", "1000"))
    ranked_k_factor: int = int(os.getenv("RANKED_K_FACTOR", "32"))
    ranked_min_reward_games: int = int(os.getenv("RANKED_MIN_REWARD_GAMES", "3"))
    max_game_stake: int = int(os.getenv("MAX_GAME_STAKE", "100"))
    mines_rtp: float = float(os.getenv("MINES_RTP", "0.92"))
    bot_release_version: str = os.getenv("BOT_RELEASE_VERSION", "2026-05-09")
    news_notification_hours: int = int(os.getenv("NEWS_NOTIFICATION_HOURS", "8"))
    quiz_ai_enabled: bool = os.getenv("QUIZ_AI_ENABLED", "1") != "0"
    game_jobs_token: str = os.getenv("GAME_JOBS_TOKEN", "")

    def __post_init__(self):
        raw = os.getenv("ADMINS", "")
        if raw:
            self.admins = [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admins


config = Config()
