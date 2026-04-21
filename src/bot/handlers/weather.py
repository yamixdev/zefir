from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from bot.keyboards.inline import weather_back, main_menu
from bot.services.weather_service import get_weather

router = Router()


class WeatherStates(StatesGroup):
    waiting_city = State()


@router.message(Command("weather"))
async def cmd_weather(message: Message, state: FSMContext):
    args = message.text.split(maxsplit=1)
    try:
        await message.delete()
    except Exception:
        pass

    if len(args) > 1:
        city = args[1]
        result = await get_weather(city)
        await message.answer(result, reply_markup=weather_back())
    else:
        await state.set_state(WeatherStates.waiting_city)
        await message.answer("⛅ Введи название города:", reply_markup=weather_back())


@router.callback_query(F.data == "weather:ask")
async def cb_weather_ask(callback: CallbackQuery, state: FSMContext):
    await state.set_state(WeatherStates.waiting_city)
    try:
        await callback.message.edit_text("⛅ Введи название города:", reply_markup=weather_back())
    except Exception:
        pass
    await state.update_data(prompt_msg_id=callback.message.message_id)
    await callback.answer()


@router.message(WeatherStates.waiting_city)
async def process_city(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()

    chat_id = message.chat.id
    city = (message.text or "").strip()

    # Delete user's input
    try:
        await message.delete()
    except Exception:
        pass

    result = await get_weather(city) if city else "❌ Пустой запрос."

    prompt_msg_id = data.get("prompt_msg_id")
    if prompt_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=prompt_msg_id,
                text=result, reply_markup=weather_back(),
            )
            return
        except Exception:
            pass
    await bot.send_message(chat_id, result, reply_markup=weather_back())
