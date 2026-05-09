from aiogram import Router

from .start import router as start_router
from .weather import router as weather_router
from .tickets import router as tickets_router
from .ai_chat import router as ai_chat_router
from .admin import router as admin_router
from .profile import router as profile_router
from .currency import router as currency_router
from .qr import router as qr_router
from .economy import router as economy_router
from .pet import router as pet_router
from .games import router as games_router
from .shop import router as shop_router
from .admin_economy import router as admin_economy_router


def setup_routers() -> Router:
    root = Router()
    root.include_router(start_router)
    root.include_router(admin_router)
    root.include_router(admin_economy_router)
    root.include_router(profile_router)
    root.include_router(economy_router)
    root.include_router(shop_router)
    root.include_router(pet_router)
    root.include_router(games_router)
    root.include_router(ai_chat_router)
    root.include_router(tickets_router)
    root.include_router(weather_router)
    root.include_router(currency_router)
    root.include_router(qr_router)
    return root
