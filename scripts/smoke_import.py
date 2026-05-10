"""Import smoke-check for production deploys.

Run from repository root after installing src/requirements.txt:
    python scripts/smoke_import.py
"""

import importlib
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("BOT_TOKEN", "123456:SMOKE_TEST_TOKEN")


MODULES = (
    "bot.db",
    "bot.config",
    "bot.handlers",
    "bot.services.economy_service",
    "bot.services.pet_service",
    "bot.services.games_service",
    "bot.services.game_logic",
    "bot.services.game_session_service",
    "bot.services.rating_service",
    "bot.services.news_service",
    "bot.services.quiz_ai_service",
    "bot.handlers.news",
    "main",
)


def main() -> None:
    for module in MODULES:
        importlib.import_module(module)
        print(f"ok: {module}")


if __name__ == "__main__":
    main()
