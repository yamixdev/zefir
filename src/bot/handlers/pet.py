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
    get_pet_home,
    get_pet,
    get_or_create_pet,
    list_pets,
    move_pet_room,
    play_pet_minigame,
    perform_pet_action,
    rename_pet,
    set_active_pet,
    ROOMS,
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
        InlineKeyboardButton(text="🎾 Играть", callback_data="pet:minigame:random"),
    )
    kb.row(
        InlineKeyboardButton(text="🤍 Гладить", callback_data="pet:act:pet"),
        InlineKeyboardButton(text="💤 Спать", callback_data="pet:act:sleep"),
    )
    kb.row(InlineKeyboardButton(text="🩹 Забота", callback_data="pet:act:heal"))
    kb.row(InlineKeyboardButton(text="🏠 Домик", callback_data="pet:home:view"))
    kb.row(InlineKeyboardButton(text="✏️ Имя", callback_data="pet:rename"))
    kb.row(InlineKeyboardButton(text="🎒 Предметы для питомца", callback_data="econ:inv:c:food"))
    kb.row(InlineKeyboardButton(text="⬅️ В развлечения", callback_data="menu:fun"))
    return kb.as_markup()


def _pet_text(pet: dict) -> str:
    cosmetic = pet.get("cosmetic_name") or "без косметики"
    sp = SPECIES.get(pet.get("species"), SPECIES["cat"])
    room = pet.get("room_label") or ROOMS.get(pet.get("room"), "комната")
    state = pet.get("state_text") or "спокойно занимается своими делами"
    return (
        f"{sp['emoji']} <b>{html.escape(pet['name'])}</b> · {sp['name']}\n\n"
        f"Уровень: <b>{pet['level']}</b>\n"
        f"Опыт: <b>{pet['xp']}</b>/след. уровень\n\n"
        f"Комната: <b>{html.escape(room)}</b>\n"
        f"Сейчас: <i>{html.escape(state)}</i>\n"
        f"Образ: <b>{html.escape(cosmetic)}</b>\n\n"
        f"Сытость: <b>{pet['hunger']}</b> {_bar(pet['hunger'])}\n"
        f"Жажда: <b>{pet['thirst']}</b> {_bar(pet['thirst'])}\n"
        f"Чистота: <b>{pet['cleanliness']}</b> {_bar(pet['cleanliness'])}\n"
        f"Настроение: <b>{pet['mood']}</b> {_bar(pet['mood'])}\n"
        f"Энергия: <b>{pet['energy']}</b> {_bar(pet['energy'])}\n\n"
        f"Здоровье: <b>{pet['health']}</b> {_bar(pet['health'])}\n"
        f"Привязанность: <b>{pet['affection']}</b> {_bar(pet['affection'])}\n\n"
        "<i>Состояние меняется со временем. Если долго не заходить, питомец устанет и заскучает.</i>"
    )


def _home_text(data: dict) -> str:
    home = data["home"]
    by_room: dict[str, list[str]] = {}
    for item in data["items"]:
        by_room.setdefault(item["room"], []).append(item_label(item))
    lines = [
        "🏠 <b>Домик питомцев</b>",
        f"Уровень домика: <b>{home['level']}</b>",
        f"Активная комната: <b>{html.escape(ROOMS.get(home['active_room'], home['active_room']))}</b>\n",
        "<b>Комнаты:</b>",
    ]
    for code, label in ROOMS.items():
        items = ", ".join(by_room.get(code, [])) or "пока пусто"
        lines.append(f"• {html.escape(label)}: {items}")
    if data["events"]:
        lines.append("\n<b>Недавние события:</b>")
        for event in data["events"][:3]:
            lines.append(f"• {html.escape(event['text'])}")
    return "\n".join(lines)


def _home_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="Кухня", callback_data="pet:room:kitchen"),
        InlineKeyboardButton(text="Спальня", callback_data="pet:room:bedroom"),
    )
    kb.row(
        InlineKeyboardButton(text="Игровая", callback_data="pet:room:playroom"),
        InlineKeyboardButton(text="Ванная", callback_data="pet:room:bathroom"),
    )
    kb.row(InlineKeyboardButton(text="Двор", callback_data="pet:room:yard"))
    kb.row(InlineKeyboardButton(text="🎒 Предметы домика", callback_data="econ:inv:c:home"))
    kb.row(InlineKeyboardButton(text="🐾 К питомцу", callback_data="pet:home"))
    return kb.as_markup()


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


@router.callback_query(F.data == "pet:home:view")
async def cb_pet_home_view(callback: CallbackQuery):
    data = await get_pet_home(callback.from_user.id)
    await smart_edit(callback, _home_text(data), reply_markup=_home_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("pet:room:"))
async def cb_pet_room(callback: CallbackQuery):
    room = callback.data.split(":")[2]
    result = await move_pet_room(callback.from_user.id, room)
    if not result["ok"]:
        await callback.answer("Сначала выбери питомца.", show_alert=True)
        return
    data = await get_pet_home(callback.from_user.id)
    await smart_edit(callback, _home_text(data), reply_markup=_home_kb())
    await callback.answer(f"Комната: {ROOMS.get(room, room)}")


@router.callback_query(F.data.startswith("pet:equip:"))
async def cb_pet_equip(callback: CallbackQuery):
    item_id = int(callback.data.split(":")[2])
    result = await equip_pet_cosmetic(callback.from_user.id, item_id)
    if not result["ok"]:
        if result.get("error") == "no_pet":
            msg = "Сначала выбери питомца."
        elif result.get("error") == "already_equipped":
            msg = "Этот предмет уже надет на питомце."
        else:
            msg = "Эту косметику нельзя надеть."
        if result.get("pet"):
            pets = await list_pets(callback.from_user.id)
            await smart_edit(callback, _pet_text(result["pet"]), reply_markup=_pet_kb(pets))
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
    if result.get("event"):
        event = result["event"]
        bonus_parts = []
        if event.get("xp"):
            bonus_parts.append(f"+{event['xp']} опыта")
        if event.get("zefirki"):
            bonus_parts.append(f"+{event['zefirki']} 🍬")
        bonus = f"\nБонус: <b>{', '.join(bonus_parts)}</b>" if bonus_parts else ""
        extra += f"\n\n🎲 <b>Случайное событие</b>\n<i>{html.escape(event['text'])}</i>{bonus}"
    text = (
        f"🐾 Ты выбрал действие: <b>{action_cfg['label']}</b>\n"
        f"Награда: <b>+{result['zefirki']}</b> 🍬{extra}\n\n"
        f"{_pet_text(pet)}"
    )
    await smart_edit(callback, text, reply_markup=_pet_kb(pets))
    await callback.answer("Готово")


@router.callback_query(F.data.startswith("pet:minigame:"))
async def cb_pet_minigame(callback: CallbackQuery):
    game_code = callback.data.split(":")[2]
    if game_code == "random":
        game_code = None
    result = await play_pet_minigame(callback.from_user.id, game_code)
    if not result["ok"]:
        if result.get("error") == "low_energy":
            await callback.answer("Питомец устал. Дай ему отдохнуть.", show_alert=True)
        elif result.get("error") == "no_pet":
            await callback.answer("Сначала выбери питомца.", show_alert=True)
        else:
            await callback.answer("Мини-игра сейчас недоступна.", show_alert=True)
        pet = result.get("pet") or await get_pet(callback.from_user.id)
        if pet:
            pets = await list_pets(callback.from_user.id)
            await smart_edit(callback, _pet_text(pet), reply_markup=_pet_kb(pets))
        return
    pet = result["pet"]
    pets = await list_pets(callback.from_user.id)
    result_label = {"great": "отлично", "good": "хорошо", "ok": "нормально"}.get(result["result"], result["result"])
    extra = f"\n\n<i>{html.escape(result['reaction'])}</i>"
    if result.get("item"):
        extra += f"\n\n🎁 Найден предмет: {item_label(result['item'])}"
    if result.get("level_up"):
        extra += "\n\n🎉 Уровень питомца вырос!"
    text = (
        f"🎮 <b>{html.escape(result['game']['name'])}</b>\n\n"
        f"Результат: <b>{result_label}</b>\n"
        f"Опыт: <b>+{result['xp']}</b>{extra}\n\n"
        f"{_pet_text(pet)}"
    )
    await smart_edit(callback, text, reply_markup=_pet_kb(pets))
    await callback.answer("Мини-игра завершена")


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
