"""Puhlyash mascot settings + test notifications."""
import aiosqlite
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from building_blocks.logger import get_logger
from database import DB_PATH

log = get_logger(__name__)
router = Router()


class PuhlyashStates(StatesGroup):
    main = State()
    edit_name = State()
    edit_specialty = State()
    edit_tone = State()


DEFAULT_PUHLYASH = {
    "name": "Пухляш",
    "specialty": "всё подряд",
    "tone": "friendly",
    "catchphrase": "Свой парень, знает толк в еде!",
    "emoji": "🍝",
}

TONES = {
    "friendly":  "😊 Дружелюбный",
    "funny":     "😂 С юморком",
    "serious":   "🧐 Серьёзный",
    "foodie":    "😍 Гурман",
}


def _main_kb():
    from bot_handlers.recipes import main_kb
    return main_kb()


async def _get_puhlyash(tg_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT puhlyash_name, puhlyash_specialty, puhlyash_tone, puhlyash_catchphrase, puhlyash_emoji "
            "FROM user_profiles WHERE tg_id=?", (tg_id,)
        ) as c:
            row = await c.fetchone()
    if not row:
        return DEFAULT_PUHLYASH.copy()
    return {
        "name": row["puhlyash_name"] or DEFAULT_PUHLYASH["name"],
        "specialty": row["puhlyash_specialty"] or DEFAULT_PUHLYASH["specialty"],
        "tone": row["puhlyash_tone"] or DEFAULT_PUHLYASH["tone"],
        "catchphrase": row["puhlyash_catchphrase"] or DEFAULT_PUHLYASH["catchphrase"],
        "emoji": row["puhlyash_emoji"] or DEFAULT_PUHLYASH["emoji"],
    }


async def _ensure_columns():
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        for col in [
            "puhlyash_name TEXT DEFAULT 'Пухляш'",
            "puhlyash_specialty TEXT DEFAULT 'всё подряд'",
            "puhlyash_tone TEXT DEFAULT 'friendly'",
            "puhlyash_catchphrase TEXT",
            "puhlyash_emoji TEXT DEFAULT '🍝'",
        ]:
            try:
                await db.execute(f"ALTER TABLE user_profiles ADD COLUMN {col}")
            except Exception:
                pass
        await db.commit()


@router.message(F.text.in_(["🍝 Пухляш", "🍝 Настройка Пухляша", "/puhlyash"]))
async def cmd_puhlyash(message: Message, state: FSMContext):
    await _ensure_columns()
    tg_id = str(message.from_user.id)
    p = await _get_puhlyash(tg_id)
    tone_label = TONES.get(p["tone"], p["tone"])

    text = (
        f"{p['emoji']} <b>Настройка {p['name']}</b>\n\n"
        f"🎨 Имя: <b>{p['name']}</b>\n"
        f"🍳 Специализация: {p['specialty']}\n"
        f"💬 Тон: {tone_label}\n"
        f"✨ Фраза: <i>{p['catchphrase']}</i>\n\n"
        f"🧪 Тест уведомлений:"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎨 Изменить имя", callback_data="ph:name"),
         InlineKeyboardButton(text=f"🍳 Специализация", callback_data="ph:spec")],
        [InlineKeyboardButton(text=f"💬 Тон общения", callback_data="ph:tone"),
         InlineKeyboardButton(text=f"✨ Фраза", callback_data="ph:catch")],
        [InlineKeyboardButton(text="🧪 Прислать тестовое уведомление", callback_data="ph:test_notify")],
        [InlineKeyboardButton(text="🍝 Получить рецепт сейчас", callback_data="ph:recipe_now")],
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "ph:test_notify")
async def test_notify(call, state: FSMContext):
    await call.answer("Отправляю...")
    tg_id = str(call.from_user.id)
    try:
        from modules.notifier.sender import send_notification
        from modules.puhlyash.persona import generate_puhlyash_recipe, format_puhlyash_message
        import asyncio
        p = await _get_puhlyash(tg_id)
        recipe = await asyncio.wait_for(generate_puhlyash_recipe(), timeout=30)
        text = (
            f"{p['emoji']} <b>Тестовое уведомление от {p['name']}</b>\n\n"
            f"{format_puhlyash_message(recipe)}"
        )
        ok = await send_notification(int(tg_id), text)
        if ok:
            await call.message.answer("✅ Отправлено! Проверь личные сообщения в Telegram → @FatBoyandGirl_bot")
        else:
            await call.message.answer("❌ Не удалось. Проверь настройки userbot'a.")
    except Exception as e:
        await call.message.answer(f"❌ Ошибка: {e}")


@router.callback_query(F.data == "ph:recipe_now")
async def recipe_now(call, state: FSMContext):
    await call.answer("🍝 Генерирую...")
    tg_id = str(call.from_user.id)
    try:
        from modules.puhlyash.persona import generate_puhlyash_recipe, format_puhlyash_message
        from modules.reactions.engine import reaction_kb
        from bot_handlers.recipes import _save
        import asyncio
        recipe = await asyncio.wait_for(generate_puhlyash_recipe(), timeout=45)
        await _save(recipe)
        text = format_puhlyash_message(recipe)
        await call.message.answer(text, parse_mode="HTML",
                                  reply_markup=reaction_kb("recipe", recipe.get("id", "")))
        await call.message.answer("👇 Как тебе?", reply_markup=_main_kb())
    except Exception as e:
        await call.message.answer(f"❌ {e}")


@router.callback_query(F.data == "ph:name")
async def edit_name(call, state: FSMContext):
    await call.answer()
    await state.set_state(PuhlyashStates.edit_name)
    await call.message.answer(
        "🎨 Как будем звать маскота?\n"
        "Напиши имя (например: Пухляш, Боря, Гурман)",
        reply_markup=ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="Пухляш")],
            [KeyboardButton(text="❌ Отмена")]
        ], resize_keyboard=True)
    )


@router.message(PuhlyashStates.edit_name)
async def got_name(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено", reply_markup=_main_kb())
    name = message.text.strip()[:30]
    tg_id = str(message.from_user.id)
    await _ensure_columns()
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute(
            "INSERT INTO user_profiles (tg_id, puhlyash_name) VALUES (?,?) "
            "ON CONFLICT(tg_id) DO UPDATE SET puhlyash_name=excluded.puhlyash_name",
            (tg_id, name)
        )
        await db.commit()
    await state.clear()
    await message.answer(f"✅ Теперь твой маскот — <b>{name}</b>!", parse_mode="HTML", reply_markup=_main_kb())


@router.callback_query(F.data == "ph:spec")
async def edit_spec(call, state: FSMContext):
    await call.answer()
    await state.set_state(PuhlyashStates.edit_specialty)
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="всё подряд"), KeyboardButton(text="итальянская кухня")],
        [KeyboardButton(text="азиатская кухня"), KeyboardButton(text="домашняя русская")],
        [KeyboardButton(text="выпечка и десерты"), KeyboardButton(text="здоровое питание")],
        [KeyboardButton(text="❌ Отмена")],
    ], resize_keyboard=True)
    await call.message.answer("🍳 На чём специализируется?", reply_markup=kb)


@router.message(PuhlyashStates.edit_specialty)
async def got_spec(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено", reply_markup=_main_kb())
    tg_id = str(message.from_user.id)
    await _ensure_columns()
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute(
            "INSERT INTO user_profiles (tg_id, puhlyash_specialty) VALUES (?,?) "
            "ON CONFLICT(tg_id) DO UPDATE SET puhlyash_specialty=excluded.puhlyash_specialty",
            (tg_id, message.text.strip())
        )
        await db.commit()
    await state.clear()
    await message.answer(f"✅ Специализация: <b>{message.text}</b>", parse_mode="HTML", reply_markup=_main_kb())


@router.callback_query(F.data == "ph:tone")
async def edit_tone_cb(call, state: FSMContext):
    await call.answer()
    await state.set_state(PuhlyashStates.edit_tone)
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=label) for label in TONES.values()],
        [KeyboardButton(text="❌ Отмена")],
    ], resize_keyboard=True)
    await call.message.answer("💬 Тон общения:", reply_markup=kb)


@router.message(PuhlyashStates.edit_tone)
async def got_tone(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено", reply_markup=_main_kb())
    tone_key = next((k for k, v in TONES.items() if v == message.text), "friendly")
    tg_id = str(message.from_user.id)
    await _ensure_columns()
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute(
            "INSERT INTO user_profiles (tg_id, puhlyash_tone) VALUES (?,?) "
            "ON CONFLICT(tg_id) DO UPDATE SET puhlyash_tone=excluded.puhlyash_tone",
            (tg_id, tone_key)
        )
        await db.commit()
    await state.clear()
    await message.answer(f"✅ Тон: <b>{message.text}</b>", parse_mode="HTML", reply_markup=_main_kb())


@router.callback_query(F.data == "ph:catch")
async def edit_catch(call, state: FSMContext):
    from aiogram.fsm.state import State
    await call.answer()
    # Используем edit_name state как generic text input
    await state.set_state(PuhlyashStates.edit_name)
    await state.update_data(editing_field="catchphrase")
    await call.message.answer(
        "✨ Напиши фразу маскота:\n"
        "Например: <i>Свой парень, знает толк в еде!</i>",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)
    )