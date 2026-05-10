from aiogram.types import CallbackQuery, User

from bot.middlewares.fun_consent import FUN_CALLBACK_PREFIXES, FunConsentMiddleware, _target_from_callback_data


def test_gamebot_callbacks_are_covered_by_fun_consent_gate():
    assert any("gamebot:".startswith(prefix) for prefix in FUN_CALLBACK_PREFIXES)
    assert _target_from_callback_data("gamebot:blackjack:25") == "games"


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
