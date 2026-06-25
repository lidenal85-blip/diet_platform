"""Bot handler: Подбор диеты — опросник + Gemini рекомендации."""
import json, sys
import aiosqlite
sys.path.insert(0, "/opt/leviathan_engine")
try:
    from llm_factory import LLMFactory
    _LEV = True
except ImportError:
    _LEV = False
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from building_blocks.logger import get_logger
from database import DB_PATH

log = get_logger(__name__)
router = Router()

SYS_DIET = """Ты диетолог и нутрициолог. Отвечай строго в JSON без текста вне JSON."""


class PickerStates(StatesGroup):
    goal = State()
    age = State()
    restrictions = State()
    activity = State()
    confirm = State()
    choosing = State()


def _main_kb():
    from bot_handlers.recipes import main_kb
    return main_kb()


def _cancel_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="❌ Отмена")]
    ], resize_keyboard=True)


def _goal_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔥 Похудеть"), KeyboardButton(text="💪 Набрать мышцы")],
        [KeyboardButton(text="⚡ Больше энергии"), KeyboardButton(text="❤️ Здоровое питание")],
        [KeyboardButton(text="🦠 Лечебная диета"), KeyboardButton(text="❌ Отмена")],
    ], resize_keyboard=True)


def _activity_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🛋 Малоподвижный"), KeyboardButton(text="🚶 Умеренный")],
        [KeyboardButton(text="🏋 Активный"), KeyboardButton(text="⚡ Очень активный")],
        [KeyboardButton(text="❌ Отмена")],
    ], resize_keyboard=True)


async def _gemini(prompt: str, system: str = SYS_DIET) -> str:
    if not _LEV:
        raise RuntimeError("LLMFactory недоступен")
    return await LLMFactory.execute_request(
        prompt=prompt,
        system=system,
        model="gemini-3.1-flash-lite",
        driver="gemini",
        fallback=True,
        task_type="structured",
    )

def _fmt_diet_card(d: dict, n: int) -> str:
    pros = "\n".join(f"  ✅ {p}" for p in d.get("pros", []))
    cons = "\n".join(f"  ⚠️ {c}" for c in d.get("cons", []))
    foods = ", ".join(d.get("key_foods", []))
    return (
        f"<b>{n}. {d['name']}</b>\n"
        f"📝 {d.get('tagline', '')}\n\n"
        f"🔥 {d.get('calories_range', '')}  |  "
        f"⏱ {d.get('duration_weeks', '?')} нед.  |  "
        f"💪 {d.get('difficulty', '')}\n\n"
        f"{pros}\n{cons}\n\n"
        f"🥗 Ключевые продукты: {foods}"
    )


def _fmt_week_plan(plan: dict, diet_name: str) -> str:
    lines = [f"📅 <b>План на неделю — {diet_name}</b>\n"]
    for day in plan.get("days", []):
        lines.append(f"<b>{day['day']}</b>")
        b = day.get("breakfast", {})
        l = day.get("lunch", {})
        d = day.get("dinner", {})
        lines.append(f"  🌅 {b.get('название', b) if isinstance(b, dict) else b} ({b.get('ккал', '?') if isinstance(b, dict) else '?'} ккал)")
        lines.append(f"  🍽 {l.get('название', l) if isinstance(l, dict) else l} ({l.get('ккал', '?') if isinstance(l, dict) else '?'} ккал)")
        lines.append(f"  🌙 {d.get('название', d) if isinstance(d, dict) else d} ({d.get('ккал', '?') if isinstance(d, dict) else '?'} ккал)")
        if day.get("snack"):
            lines.append(f"  🍎 Перекус: {day['snack']}")
        lines.append("")
    shop = plan.get("shopping_list", [])
    if shop:
        lines.append("🛒 <b>Список покупок:</b>")
        lines += [f"  • {s}" for s in shop]
    tips = plan.get("tips", [])
    if tips:
        lines.append("\n💡 <b>Советы:</b>")
        lines += [f"  • {t}" for t in tips]
    return "\n".join(lines)


# ── Хендлеры ──────────────────────────────────────────────

@router.message(F.text.in_(["🎯 Подобрать диету", "🔍 Найти диету"]))
async def btn_pick_diet(message: Message, state: FSMContext):
    await state.set_state(PickerStates.goal)
    await message.answer(
        "🎯 <b>Подбор диеты</b>\n\n"
        "Шаг 1 из 4. Какая главная цель?",
        parse_mode="HTML", reply_markup=_goal_kb()
    )


GOALS = ["🔥 Похудеть", "💪 Набрать мышцы",
         "⚡ Больше энергии", "❤️ Здоровое питание", "🦠 Лечебная диета"]


@router.message(PickerStates.goal)
async def got_goal(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено", reply_markup=_main_kb())
    await state.update_data(goal=message.text)
    await state.set_state(PickerStates.age)
    await message.answer(
        "👤 Шаг 2 из 4. Сколько тебе лет?\n"
        "Напиши цифру, например: <code>28</code>",
        parse_mode="HTML", reply_markup=_cancel_kb()
    )


@router.message(PickerStates.age)
async def got_age(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено", reply_markup=_main_kb())
    digits = "".join(filter(str.isdigit, message.text or ""))
    if not digits or not (10 <= int(digits) <= 100):
        return await message.answer("Напиши возраст, например: <code>28</code>", parse_mode="HTML")
    await state.update_data(age=int(digits))
    await state.set_state(PickerStates.restrictions)
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Нет ограничений")],
        [KeyboardButton(text="Без глютена"), KeyboardButton(text="Без лактозы")],
        [KeyboardButton(text="Вегетарианство"), KeyboardButton(text="Диабет")],
        [KeyboardButton(text="❌ Отмена")],
    ], resize_keyboard=True)
    await message.answer(
        "🥑 Шаг 3 из 4. Есть ограничения в еде?\n"
        "Выбери или напиши своё:",
        parse_mode="HTML", reply_markup=kb
    )


@router.message(PickerStates.restrictions)
async def got_restrictions(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено", reply_markup=_main_kb())
    await state.update_data(restrictions=message.text)
    await state.set_state(PickerStates.activity)
    await message.answer(
        "🏋 Шаг 4 из 4. Уровень физической активности:",
        parse_mode="HTML", reply_markup=_activity_kb()
    )


@router.message(PickerStates.activity)
async def got_activity(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено", reply_markup=_main_kb())
    data = await state.get_data()
    data["activity"] = message.text
    await state.update_data(activity=message.text)
    await state.set_state(PickerStates.confirm)

    # Сохраняем профиль в БД
    tg_id = str(message.from_user.id)
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute(
            "INSERT INTO user_profiles (tg_id, goal, age, onboarding_done) VALUES (?,?,?,1) "
            "ON CONFLICT(tg_id) DO UPDATE SET goal=excluded.goal, age=excluded.age, onboarding_done=1",
            (tg_id, data.get("goal", ""), data.get("age", 0))
        )
        await db.commit()

    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🚀 Подбирай!"), KeyboardButton(text="❌ Отмена")]
    ], resize_keyboard=True)
    await message.answer(
        f"📋 <b>Твой профиль:</b>\n"
        f"🎯 Цель: {data.get('goal')}\n"
        f"👤 Возраст: {data.get('age')} лет\n"
        f"🥑 Ограничения: {data.get('restrictions')}\n"
        f"🏋 Активность: {data.get('activity')}\n\n"
        "Подобрать 3 варианта диеты?",
        parse_mode="HTML", reply_markup=kb
    )


@router.message(PickerStates.confirm, F.text == "🚀 Подбирай!")
async def do_pick(message: Message, state: FSMContext):
    data = await state.get_data()
    msg = await message.answer("⏳ Анализирую твой профиль, подбираю 3 диеты…", reply_markup=_main_kb())
    try:
        import asyncio
        diets = await asyncio.wait_for(_get_3_diets(data), timeout=60)
        await state.update_data(diets=diets)
        await state.set_state(PickerStates.choosing)

        # Отправляем 3 карточки
        cards = "\n\n".join(_fmt_diet_card(d, i+1) for i, d in enumerate(diets))
        await msg.delete()

        # Кнопки выбора
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text=f"1️⃣ {diets[0]['name']}")],
            [KeyboardButton(text=f"2️⃣ {diets[1]['name']}")],
            [KeyboardButton(text=f"3️⃣ {diets[2]['name']}")],
            [KeyboardButton(text="❌ Отмена")],
        ], resize_keyboard=True)

        await message.answer(
            f"🎯 <b>Твои 3 варианта:</b>\n\n{cards}\n\n"
            "Выбери диету или напиши свой вариант:",
            parse_mode="HTML", reply_markup=kb
        )
    except Exception as e:
        log.error("diet picker: %s", e)
        await message.answer(f"❌ Ошибка: {e}", reply_markup=_main_kb())


@router.message(PickerStates.choosing)
async def chose_diet(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено", reply_markup=_main_kb())

    data = await state.get_data()
    diets = data.get("diets", [])

    # Определяем выбранную диету
    chosen = None
    for i, d in enumerate(diets):
        if message.text.startswith(f"{i+1}️⃣") or d["name"].lower() in message.text.lower():
            chosen = d
            break
    if not chosen:
        # Свой вариант от пользователя
        chosen = {"name": message.text.strip()}

    await state.clear()
    diet_name = chosen["name"]

    # Сохраняем выбор в БД
    tg_id = str(message.from_user.id)
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute(
            "UPDATE user_profiles SET active_diet_mode='home' WHERE tg_id=?", (tg_id,)
        )
        await db.commit()

    msg = await message.answer(
        f"✅ Выбрана <b>{diet_name}</b>!\n"
        f"⏳ Генерирую план питания на неделю…",
        parse_mode="HTML", reply_markup=_main_kb()
    )
    try:
        import asyncio
        plan = await asyncio.wait_for(_get_week_plan(diet_name, data), timeout=60)
        text = _fmt_week_plan(plan, diet_name)
        await msg.delete()
        # Длинный текст бьём частями
        for chunk in [text[i:i+3800] for i in range(0, len(text), 3800)]:
            await message.answer(chunk, parse_mode="HTML", reply_markup=_main_kb())
    except Exception as e:
        log.error("week plan: %s", e)
        await message.answer(f"❌ Ошибка плана: {e}", reply_markup=_main_kb())


@router.message(PickerStates.confirm, F.text == "❌ Отмена")
async def cancel_confirm(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено", reply_markup=_main_kb())