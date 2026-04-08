from aiogram import Router, F
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
    await callback.message.edit_text("⛅ Введи название города:", reply_markup=weather_back())
    await callback.answer()


@router.message(WeatherStates.waiting_city)
async def process_city(message: Message, state: FSMContext):
    await state.clear()
    result = await get_weather(message.text.strip())
    await message.answer(result, reply_markup=weather_back())
