from aiogram.types import CallbackQuery, User

from bot.middlewares.fun_consent import FunConsentMiddleware


async def test_admin_profile_callback_bypasses_fun_consent():
    called = False

    async def handler(event, data):
        nonlocal called
        called = True
        return "ok"

    event = CallbackQuery(
        id="cb1",
        from_user=User(id=501, is_bot=False, first_name="Admin"),
        chat_instance="chat",
        data="profile:admin",
    )

    result = await FunConsentMiddleware()(handler, event, {})

    assert called is True
    assert result == "ok"
