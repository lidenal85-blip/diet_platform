"""Meal schedule v2 — все приёмы пищи в одном месте с именами."""
import uuid, re
import aiosqlite
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from building_blocks.logger import get_logger
from database import DB_PATH

log = get_logger(__name__)
router = Router()
TIME_RE = re.compile(r'^([01]?\d|2[0-3]):([0-5]\d)$')

DEFAULT_MEALS = [
    ("🌅 Завтрак", "07:30"),
    ("☕ Второй завтрак", "10:30"),
    ("🍽 Обед", "13:00"),
    ("🍎 Полдник", "16:00"),
    ("🌙 Ужин", "19:30"),
]


class MealScheduleStates(StatesGroup):
    main = State()
    adding_name = State()
    adding_time = State()
    editing_time = State()


def _main_kb():
    from bot_handlers.recipes import main_kb
    return main_kb()


async def _get_meals(tg_id: str) -> list:
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM meal_schedule WHERE tg_id=? ORDER BY sort_order, meal_time", (tg_id,)
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def _meals_text_kb(tg_id: str):
    meals = await _get_meals(tg_id)
    if not meals:
        text = "⏰ <b>Расписание питания</b>\n\nПриёмов пищи пока нет. Добавь свои или загрузи стандартное."
    else:
        lines = ["⏰ <b>Расписание питания</b>\n"]
        for m in meals:
            s = "✅" if m["enabled"] else "⏸"
            lines.append(f"{s} {m['meal_name']} — <b>{m['meal_time']}</b>")
        text = "\n".join(lines)

    rows = []
    for m in meals:
        tog = "⏸" if m["enabled"] else "▶️"
        rows.append([
            InlineKeyboardButton(text=f"✏️ {m['meal_name']}", callback_data=f"m:edit:{m['id']}"),
            InlineKeyboardButton(text=tog, callback_data=f"m:tog:{m['id']}"),
            InlineKeyboardButton(text="🗑", callback_data=f"m:del:{m['id']}"),
        ])
    rows.append([
        InlineKeyboardButton(text="➕ Добавить", callback_data="m:add"),
        InlineKeyboardButton(text="📋 Стандартное", callback_data="m:default"),
    ])
    rows.append([InlineKeyboardButton(text="✅ Готово", callback_data="m:done")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text.in_(["⏰ Расписание", "/schedule"]))
async def cmd_schedule(message: Message, state: FSMContext):
    await state.set_state(MealScheduleStates.main)
    text, kb = await _meals_text_kb(str(message.from_user.id))
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "m:add")
async def meal_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(MealScheduleStates.adding_name)
    await call.answer()
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🌅 Завтрак"), KeyboardButton(text="☕ Перекус")],
        [KeyboardButton(text="🍽 Обед"), KeyboardButton(text="🍎 Полдник")],
        [KeyboardButton(text="🌙 Ужин"), KeyboardButton(text="🍵 Вечерний чай")],
        [KeyboardButton(text="❌ Отмена")],
    ], resize_keyboard=True)
    await call.message.answer("📝 Название приёма пищи (выбери или напиши своё):", reply_markup=kb)


@router.message(MealScheduleStates.adding_name)
async def meal_got_name(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.set_state(MealScheduleStates.main)
        text, kb = await _meals_text_kb(str(message.from_user.id))
        return await message.answer(text, parse_mode="HTML", reply_markup=kb)
    await state.update_data(new_meal_name=message.text.strip())
    await state.set_state(MealScheduleStates.adding_time)
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="07:00"), KeyboardButton(text="08:00"), KeyboardButton(text="09:00")],
        [KeyboardButton(text="12:00"), KeyboardButton(text="13:00"), KeyboardButton(text="14:00")],
        [KeyboardButton(text="17:00"), KeyboardButton(text="18:00"), KeyboardButton(text="19:00")],
        [KeyboardButton(text="❌ Отмена")],
    ], resize_keyboard=True)
    await message.answer(
        f"⏰ Время для <b>{message.text}</b>? Формат: <code>08:30</code>",
        parse_mode="HTML", reply_markup=kb
    )


@router.message(MealScheduleStates.adding_time)
async def meal_got_time(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.set_state(MealScheduleStates.main)
        text, kb = await _meals_text_kb(str(message.from_user.id))
        return await message.answer(text, parse_mode="HTML", reply_markup=kb)
    t = message.text.strip().replace(".", ":")
    if not TIME_RE.match(t):
        return await message.answer("⚠️ Формат: <code>08:30</code>", parse_mode="HTML")
    h, m = t.split(":")
    time_str = f"{int(h):02d}:{int(m):02d}"
    data = await state.get_data()
    name = data.get("new_meal_name", "Приём пищи")
    tg_id = str(message.from_user.id)
    meals = await _get_meals(tg_id)
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute(
            "INSERT INTO meal_schedule (id,tg_id,meal_name,meal_time,enabled,sort_order) VALUES (?,?,?,?,1,?)",
            (str(uuid.uuid4()), tg_id, name, time_str, len(meals))
        )
        await db.commit()
    await _schedule_meal(tg_id, name, time_str)
    await state.set_state(MealScheduleStates.main)
    text, kb = await _meals_text_kb(tg_id)
    await message.answer(f"✅ Добавлен <b>{name}</b> в {time_str}", parse_mode="HTML", reply_markup=_main_kb())
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "m:default")
async def meal_default(call: CallbackQuery, state: FSMContext):
    tg_id = str(call.from_user.id)
    await call.answer("Загружаю стандартное расписание...")
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute("DELETE FROM meal_schedule WHERE tg_id=?", (tg_id,))
        for i, (name, time_str) in enumerate(DEFAULT_MEALS):
            await db.execute(
                "INSERT INTO meal_schedule (id,tg_id,meal_name,meal_time,enabled,sort_order) VALUES (?,?,?,?,1,?)",
                (str(uuid.uuid4()), tg_id, name, time_str, i)
            )
        await db.commit()
    for name, time_str in DEFAULT_MEALS:
        await _schedule_meal(tg_id, name, time_str)
    text, kb = await _meals_text_kb(tg_id)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("m:tog:"))
async def meal_toggle(call: CallbackQuery, state: FSMContext):
    meal_id = call.data[6:]
    tg_id = str(call.from_user.id)
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        async with db.execute("SELECT enabled FROM meal_schedule WHERE id=?", (meal_id,)) as c:
            row = await c.fetchone()
        if not row: return await call.answer("?")
        new = 1 - (row[0] or 0)
        await db.execute("UPDATE meal_schedule SET enabled=? WHERE id=?", (new, meal_id))
        await db.commit()
    await call.answer("✅" if new else "⏸")
    text, kb = await _meals_text_kb(tg_id)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("m:del:"))
async def meal_delete(call: CallbackQuery, state: FSMContext):
    meal_id = call.data[6:]
    tg_id = str(call.from_user.id)
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        async with db.execute("SELECT meal_name FROM meal_schedule WHERE id=?", (meal_id,)) as c:
            row = await c.fetchone()
        if row:
            try:
                from modules.scheduler.meal_scheduler import scheduler
                jid = f"meal_{tg_id}_{row[0]}"
                if scheduler.get_job(jid): scheduler.remove_job(jid)
            except Exception: pass
        await db.execute("DELETE FROM meal_schedule WHERE id=?", (meal_id,))
        await db.commit()
    await call.answer("🗑 Удалено")
    text, kb = await _meals_text_kb(tg_id)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("m:edit:"))
async def meal_edit(call: CallbackQuery, state: FSMContext):
    meal_id = call.data[7:]
    await state.set_state(MealScheduleStates.editing_time)
    await state.update_data(editing_id=meal_id)
    await call.answer()
    await call.message.answer(
        "⏰ Новое время (<code>08:30</code>):", parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)
    )


@router.message(MealScheduleStates.editing_time)
async def meal_edit_time(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.set_state(MealScheduleStates.main)
        text, kb = await _meals_text_kb(str(message.from_user.id))
        return await message.answer(text, parse_mode="HTML", reply_markup=kb)
    t = message.text.strip().replace(".", ":")
    if not TIME_RE.match(t):
        return await message.answer("⚠️ Формат: <code>08:30</code>", parse_mode="HTML")
    h, m = t.split(":")
    time_str = f"{int(h):02d}:{int(m):02d}"
    data = await state.get_data()
    meal_id = data.get("editing_id")
    tg_id = str(message.from_user.id)
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        async with db.execute("SELECT meal_name FROM meal_schedule WHERE id=?", (meal_id,)) as c:
            row = await c.fetchone()
        await db.execute("UPDATE meal_schedule SET meal_time=? WHERE id=?", (time_str, meal_id))
        await db.commit()
        if row: await _schedule_meal(tg_id, row[0], time_str)
    await state.set_state(MealScheduleStates.main)
    text, kb = await _meals_text_kb(tg_id)
    await message.answer(f"✅ Время обновлено: {time_str}", reply_markup=_main_kb())
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "m:done")
async def meal_done(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer("✅ Сохранено!")
    await call.message.answer("✅ Расписание готово!", reply_markup=_main_kb())


async def _schedule_meal(tg_id: str, meal_name: str, time_str: str):
    try:
        from modules.scheduler.meal_scheduler import scheduler
        from apscheduler.triggers.cron import CronTrigger
        from modules.notifier.sender import send_notification
        from modules.puhlyash.persona import generate_puhlyash_recipe, format_puhlyash_message
        import aiosqlite
        from database import DB_PATH as _DB

        job_id = f"meal_{tg_id}_{meal_name}"
        if scheduler.get_job(job_id): scheduler.remove_job(job_id)

        async def _fire(uid=tg_id, name=meal_name):
            async with aiosqlite.connect(_DB) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT enabled FROM meal_schedule WHERE tg_id=? AND meal_name=?", (uid, name)
                ) as c:
                    row = await c.fetchone()
            if not row or not row["enabled"]: return
            async with aiosqlite.connect(_DB) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM user_profiles WHERE tg_id=?", (uid,)) as c:
                    prof = await c.fetchone()
            if not prof: return
            prof = dict(prof)
            if not prof.get("notify_personal", 1) or not prof.get("notify_meals", 1): return
            recipe = await generate_puhlyash_recipe(profile=prof)
            from modules.fitness.engine import generate_exercises, format_exercises
            exercises = await generate_exercises("lunch", prof.get("active_diet_mode") or "home")
            text = (
                f"⏰ <b>{name}!</b>\n\n"
                f"{format_puhlyash_message(recipe)}\n\n"
                f"{format_exercises(exercises)}"
            )
            await send_notification(uid, text)

        h, m = time_str.split(":")
        scheduler.add_job(_fire, CronTrigger(hour=int(h), minute=int(m), timezone="Europe/Moscow"),
                          id=job_id, replace_existing=True)
        log.info("Scheduled meal '%s' for %s at %s", meal_name, tg_id, time_str)
    except Exception as e:
        log.error("_schedule_meal: %s", e)