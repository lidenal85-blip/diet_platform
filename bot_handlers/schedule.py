"""Bot handler: настройка расписания питания."""
import re
import aiosqlite
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from building_blocks.logger import get_logger
from database import DB_PATH
from modules.scheduler.meal_scheduler import reschedule_user

log = get_logger(__name__)
router = Router()

TIME_RE = re.compile(r'^([01]?\d|2[0-3]):([0-5]\d)$')


class ScheduleStates(StatesGroup):
    breakfast = State()
    lunch = State()
    dinner = State()
    confirm = State()


def _main_kb():
    from bot_handlers.recipes import main_kb
    return main_kb()


def _skip_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="⏭️ Пропустить")],
        [KeyboardButton(text="❌ Отмена")],
    ], resize_keyboard=True)


@router.message(F.text.in_(["⏰ Расписание", "/schedule"]))
async def cmd_schedule(message: Message, state: FSMContext):
    tg_id = str(message.from_user.id)
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT meal_breakfast, meal_lunch, meal_dinner FROM user_profiles WHERE tg_id=?",
            (tg_id,)
        ) as cur:
            row = await cur.fetchone()

    current = ""
    if row:
        b = row["meal_breakfast"] or "—"
        l = row["meal_lunch"] or "—"
        d = row["meal_dinner"] or "—"
        current = f"\n\nТекущее: Завтрак {b} | Обед {l} | Ужин {d}"

    await state.set_state(ScheduleStates.breakfast)
    await message.answer(
        f"⏰ <b>Настройка расписания питания</b>{current}\n\n"
        "🌅 В какое время завтрак?\n"
        "Напиши время в формате <code>08:30</code> или пропусти",
        parse_mode="HTML", reply_markup=_skip_kb()
    )


def _validate_time(text: str) -> str | None:
    text = text.strip().replace(".", ":")
    if TIME_RE.match(text):
        h, m = text.split(":")
        return f"{int(h):02d}:{int(m):02d}"
    return None


@router.message(ScheduleStates.breakfast)
async def got_breakfast(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено", reply_markup=_main_kb())
        return
    t = None if message.text == "⏭️ Пропустить" else _validate_time(message.text)
    if message.text != "⏭️ Пропустить" and t is None:
        await message.answer("Формат: <code>08:30</code>", parse_mode="HTML")
        return
    await state.update_data(breakfast=t)
    await state.set_state(ScheduleStates.lunch)
    await message.answer(
        "🍽 Обед — в которое время?\n"
        "Например: <code>13:00</code> или пропусти",
        parse_mode="HTML", reply_markup=_skip_kb()
    )


@router.message(ScheduleStates.lunch)
async def got_lunch(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено", reply_markup=_main_kb())
        return
    t = None if message.text == "⏭️ Пропустить" else _validate_time(message.text)
    if message.text != "⏭️ Пропустить" and t is None:
        await message.answer("Формат: <code>13:00</code>", parse_mode="HTML")
        return
    await state.update_data(lunch=t)
    await state.set_state(ScheduleStates.dinner)
    await message.answer(
        "🌙 Ужин — время?\nНапример: <code>19:00</code> или пропусти",
        parse_mode="HTML", reply_markup=_skip_kb()
    )


@router.message(ScheduleStates.dinner)
async def got_dinner(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено", reply_markup=_main_kb())
        return
    t = None if message.text == "⏭️ Пропустить" else _validate_time(message.text)
    if message.text != "⏭️ Пропустить" and t is None:
        await message.answer("Формат: <code>19:00</code>", parse_mode="HTML")
        return
    data = await state.get_data()
    data["dinner"] = t
    await state.update_data(dinner=t)

    b = data.get("breakfast") or "—"
    l = data.get("lunch") or "—"
    d = data.get("dinner") or "—"

    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="✅ Сохранить"), KeyboardButton(text="❌ Отмена")]
    ], resize_keyboard=True)

    await state.set_state(ScheduleStates.confirm)
    await message.answer(
        f"⏰ <b>Расписание:</b>\n"
        f"🌅 Завтрак: {b}\n"
        f"🍽 Обед: {l}\n"
        f"🌙 Ужин: {d}\n\n"
        "Буду слать рецепт + упражнения в это время. Сохранить?",
        parse_mode="HTML", reply_markup=kb
    )


@router.message(ScheduleStates.confirm, F.text == "✅ Сохранить")
async def confirm_schedule(message: Message, state: FSMContext):
    data = await state.get_data()
    tg_id = str(message.from_user.id)
    b = data.get("breakfast")
    l = data.get("lunch")
    d = data.get("dinner")
    await state.clear()

    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute(
            "INSERT INTO user_profiles (tg_id, meal_breakfast, meal_lunch, meal_dinner, notifications_enabled) "
            "VALUES (?,?,?,?,1) ON CONFLICT(tg_id) DO UPDATE SET "
            "meal_breakfast=excluded.meal_breakfast, meal_lunch=excluded.meal_lunch, "
            "meal_dinner=excluded.meal_dinner, notifications_enabled=1",
            (tg_id, b, l, d)
        )
        await db.commit()

    await reschedule_user(tg_id, b or "", l or "", d or "")
    await message.answer(
        "✅ <b>Расписание сохранено!</b>\n"
        "Буду слать рецепт и упражнения перед каждым приёмом пищи ❤️",
        parse_mode="HTML", reply_markup=_main_kb()
    )


@router.message(ScheduleStates.confirm, F.text == "❌ Отмена")
async def cancel_schedule(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено", reply_markup=_main_kb())


@router.message(F.text == "🔕 Пауза уведомлений")
async def pause_notifications(message: Message):
    tg_id = str(message.from_user.id)
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute(
            "UPDATE user_profiles SET notifications_enabled=0 WHERE tg_id=?", (tg_id,)
        )
        await db.commit()
    await message.answer("🔕 Уведомления пауза. Включить: /schedule", reply_markup=_main_kb())