import html

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.economy_service import item_label
from bot.services.pet_service import (
    PET_ACTIONS,
    SPECIES,
    create_pet,
    equip_pet_cosmetic,
    get_pet,
    get_or_create_pet,
    list_pets,
    perform_pet_action,
    rename_pet,
    set_active_pet,
)
from bot.utils import render_clean_message, smart_edit

router = Router()


class PetStates(StatesGroup):
    waiting_name = State()


def _bar(value: int) -> str:
    filled = max(0, min(5, round(value / 20)))
    return "■" * filled + "□" * (5 - filled)


def _species_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🐱 Котик", callback_data="pet:choose:cat"),
            InlineKeyboardButton(text="🐶 Пёсель", callback_data="pet:choose:dog"),
        ],
        [InlineKeyboardButton(text="🐿 Рыжая белочка", callback_data="pet:choose:squirrel")],
        [InlineKeyboardButton(text="⬅️ В развлечения", callback_data="menu:fun")],
    ])


def _pet_kb(pets: list[dict] | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if pets and len(pets) > 1:
        for pet in pets[:6]:
            sp = SPECIES.get(pet.get("species"), SPECIES["cat"])
            marker = "✅ " if pet.get("active") else ""
            kb.row(InlineKeyboardButton(
                text=f"{marker}{sp['emoji']} {pet['name']}",
                callback_data=f"pet:switch:{pet['id']}",
            ))
    kb.row(
        InlineKeyboardButton(text="🍽 Еда", callback_data="pet:act:feed"),
        InlineKeyboardButton(text="💧 Вода", callback_data="pet:act:drink"),
    )
    kb.row(
        InlineKeyboardButton(text="🧼 Мыть", callback_data="pet:act:wash"),
        InlineKeyboardButton(text="🎾 Играть", callback_data="pet:act:play"),
    )
    kb.row(
        InlineKeyboardButton(text="🤍 Гладить", callback_data="pet:act:pet"),
        InlineKeyboardButton(text="💤 Спать", callback_data="pet:act:sleep"),
    )
    kb.row(InlineKeyboardButton(text="🩹 Забота", callback_data="pet:act:heal"))
    kb.row(InlineKeyboardButton(text="✏️ Имя", callback_data="pet:rename"))
    kb.row(InlineKeyboardButton(text="🎒 Предметы для питомца", callback_data="econ:inv:c:food"))
    kb.row(InlineKeyboardButton(text="⬅️ В развлечения", callback_data="menu:fun"))
    return kb.as_markup()


def _pet_text(pet: dict) -> str:
    cosmetic = pet.get("cosmetic_name") or "без косметики"
    sp = SPECIES.get(pet.get("species"), SPECIES["cat"])
    return (
        f"{sp['emoji']} <b>{html.escape(pet['name'])}</b> · {sp['name']}\n\n"
        f"Уровень: <b>{pet['level']}</b>\n"
        f"Опыт: <b>{pet['xp']}</b>/след. уровень\n\n"
        f"Образ: <b>{html.escape(cosmetic)}</b>\n\n"
        f"Сытость: <b>{pet['hunger']}</b> {_bar(pet['hunger'])}\n"
        f"Жажда: <b>{pet['thirst']}</b> {_bar(pet['thirst'])}\n"
        f"Чистота: <b>{pet['cleanliness']}</b> {_bar(pet['cleanliness'])}\n"
        f"Настроение: <b>{pet['mood']}</b> {_bar(pet['mood'])}\n"
        f"Энергия: <b>{pet['energy']}</b> {_bar(pet['energy'])}\n\n"
        f"Здоровье: <b>{pet['health']}</b> {_bar(pet['health'])}\n"
        f"Привязанность: <b>{pet['affection']}</b> {_bar(pet['affection'])}\n\n"
        "<i>Каждое действие можно сделать один раз в день.</i>"
    )


@router.callback_query(F.data == "pet:home")
async def cb_pet_home(callback: CallbackQuery):
    pet = await get_pet(callback.from_user.id)
    pets = await list_pets(callback.from_user.id)
    if not pet:
        await smart_edit(
            callback,
            "🐾 <b>Выбор питомца</b>\n\n"
            "Для начала можно завести одного. Остальных позже будем открывать через уровень, кейсы и редкие предметы.",
            reply_markup=_species_kb(),
        )
        await callback.answer()
        return
    await smart_edit(callback, _pet_text(pet), reply_markup=_pet_kb(pets))
    await callback.answer()


@router.callback_query(F.data.startswith("pet:choose:"))
async def cb_pet_choose(callback: CallbackQuery):
    species = callback.data.split(":")[2]
    pet = await create_pet(callback.from_user.id, species)
    pets = await list_pets(callback.from_user.id)
    await smart_edit(callback, _pet_text(pet), reply_markup=_pet_kb(pets))
    await callback.answer("Питомец поселился у тебя")


@router.callback_query(F.data.startswith("pet:switch:"))
async def cb_pet_switch(callback: CallbackQuery):
    pet_id = int(callback.data.split(":")[2])
    pet = await set_active_pet(callback.from_user.id, pet_id)
    if not pet:
        await callback.answer("Питомец не найден.", show_alert=True)
        return
    pets = await list_pets(callback.from_user.id)
    await smart_edit(callback, _pet_text(pet), reply_markup=_pet_kb(pets))
    await callback.answer("Активный питомец изменён")


@router.callback_query(F.data.startswith("pet:equip:"))
async def cb_pet_equip(callback: CallbackQuery):
    item_id = int(callback.data.split(":")[2])
    result = await equip_pet_cosmetic(callback.from_user.id, item_id)
    if not result["ok"]:
        msg = "Сначала выбери питомца." if result.get("error") == "no_pet" else "Эту косметику нельзя надеть."
        await callback.answer(msg, show_alert=True)
        return
    pets = await list_pets(callback.from_user.id)
    await smart_edit(callback, _pet_text(result["pet"]), reply_markup=_pet_kb(pets))
    await callback.answer(f"Надето: {result['item']['name']}", show_alert=True)


@router.message(Command("pet"))
async def cmd_pet(message: Message, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    pet = await get_pet(message.from_user.id)
    pets = await list_pets(message.from_user.id)
    if not pet:
        await render_clean_message(
            bot,
            message.chat.id,
            message.from_user.id,
            "🐾 <b>Выбор питомца</b>\n\nДля начала выбери первого спутника.",
            reply_markup=_species_kb(),
        )
        return
    await render_clean_message(bot, message.chat.id, message.from_user.id, _pet_text(pet), reply_markup=_pet_kb(pets))


@router.callback_query(F.data.startswith("pet:act:"))
async def cb_pet_action(callback: CallbackQuery):
    action = callback.data.split(":")[2]
    result = await perform_pet_action(callback.from_user.id, action)
    if not result["ok"]:
        if result.get("error") == "already_done":
            await callback.answer("Это действие уже было сегодня.", show_alert=True)
        elif result.get("error") == "low_energy":
            await callback.answer("Не хватает энергии для тренировки.", show_alert=True)
        elif result.get("error") == "no_pet":
            await smart_edit(
                callback,
                "🐾 <b>Выбор питомца</b>\n\nСначала выбери первого спутника.",
                reply_markup=_species_kb(),
            )
            await callback.answer("Сначала выбери питомца.", show_alert=True)
            return
        else:
            await callback.answer("Действие недоступно.", show_alert=True)
        pet = result.get("pet") or await get_pet(callback.from_user.id)
        if pet:
            pets = await list_pets(callback.from_user.id)
            await smart_edit(callback, _pet_text(pet), reply_markup=_pet_kb(pets))
        return

    pet = result["pet"]
    pets = await list_pets(callback.from_user.id)
    action_cfg = result["action"]
    extra = ""
    if result.get("reaction"):
        extra += f"\n\n<i>{html.escape(result['reaction'])}</i>"
    if result["level_up"]:
        extra += "\n\n🎉 Уровень питомца вырос!"
    if result.get("item"):
        extra += f"\n\n🎁 Найден предмет: {item_label(result['item'])}"
    text = (
        f"🐾 Ты выбрал действие: <b>{action_cfg['label']}</b>\n"
        f"Награда: <b>+{result['zefirki']}</b> 🍬{extra}\n\n"
        f"{_pet_text(pet)}"
    )
    await smart_edit(callback, text, reply_markup=_pet_kb(pets))
    await callback.answer("Готово")


@router.callback_query(F.data == "pet:rename")
async def cb_pet_rename(callback: CallbackQuery, state: FSMContext):
    if not await get_or_create_pet(callback.from_user.id):
        await smart_edit(
            callback,
            "🐾 <b>Выбор питомца</b>\n\nСначала выбери первого спутника.",
            reply_markup=_species_kb(),
        )
        await callback.answer("Сначала выбери питомца.", show_alert=True)
        return
    await state.set_state(PetStates.waiting_name)
    await state.update_data(prompt_msg_id=callback.message.message_id)
    await smart_edit(
        callback,
        "✏️ <b>Имя питомца</b>\n\nНапиши новое имя до 24 символов:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="pet:home")]
        ]),
    )
    await callback.answer()


@router.message(PetStates.waiting_name)
async def msg_pet_name(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    prompt_msg_id = data.get("prompt_msg_id")
    name = (message.text or "").strip()
    try:
        await message.delete()
    except Exception:
        pass
    pet = await rename_pet(message.from_user.id, name)
    if not pet:
        return
    await state.clear()
    pets = await list_pets(message.from_user.id)
    if prompt_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=prompt_msg_id,
                text=_pet_text(pet),
                reply_markup=_pet_kb(pets),
            )
        except Exception:
            pass
