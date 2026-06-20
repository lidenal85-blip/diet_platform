"""Bot handler: Личный кабинет пользователя."""
import aiosqlite
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from building_blocks.logger import get_logger
from database import DB_PATH

log = get_logger(__name__)
router = Router()

LEVELS = {
    "🥚 Новичок": "beginner",
    "🍳 Любитель": "amateur",
    "👨‍🍳 Готовлю с удовольствием": "cook",
    "🌟 Эксперт": "expert",
}
EXPS = {
    "🔒 Только проверенное": "classic",
    "⚡ Иногда что-то новое": "sometimes",
    "🚀 Люблю пробовать": "explorer",
}
BUDGETS = {
    "🎓 Студенческий": "student",
    "💰 Обычный": "normal",
    "💳 Не считаю": "free",
}
TIMES = {
    "⏱ До 15 мин": 15,
    "⏰ До 30 мин": 30,
    "☕ Сколько надо": 60,
}


class CabinetStates(StatesGroup):
    level = State()
    experiment = State()
    budget = State()
    time = State()
    exclude = State()
    recipe_day_time = State()


def _kb(options: list, cancel=True) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=o)] for o in options]
    if cancel:
        rows.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def _main_kb():
    from bot_handlers.recipes import main_kb
    return main_kb()


async def _get_profile(tg_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT cook_level,experiment_level,budget_level,max_cook_time,"
            "excluded_foods,recipe_day_time,recipe_day_enabled FROM user_profiles WHERE tg_id=?",
            (tg_id,)
        ) as c:
            r = await c.fetchone()
    return dict(r) if r else {}


def _profile_text(p: dict) -> str:
    lvl_map = {v: k for k, v in LEVELS.items()}
    exp_map = {v: k for k, v in EXPS.items()}
    bud_map = {v: k for k, v in BUDGETS.items()}
    time_map = {v: k for k, v in TIMES.items()}
    excl = p.get('excluded_foods', '') or 'нет'
    rdt = p.get('recipe_day_time') or 'не задано'
    rde = '✅ включён' if p.get('recipe_day_enabled') else '❌ выключен'
    return (
        f"👨‍🍳 <b>Твой кабинет</b>\n\n"
        f"🍳 Уровень: {lvl_map.get(p.get('cook_level','beginner'), 'Новичок')}\n"
        f"🚀 Эксперименты: {exp_map.get(p.get('experiment_level','sometimes'), '')}\n"
        f"💰 Бюджет: {bud_map.get(p.get('budget_level','normal'), '')}\n"
        f"⏱ Время: {time_map.get(p.get('max_cook_time', 30), '')}\n"
        f"🚫 Исключения: {excl}\n"
        f"🍝 Рецепт дня: {rde}, {rdt}\n\n"
        f"🌐 <a href='https://leviathanstory.ru/diet/cabinet'>Открыть в браузере</a>"
    )


@router.message(F.text.in_(["👤 Кабинет", "/cabinet"]))
async def cmd_cabinet(message: Message, state: FSMContext):
    p = await _get_profile(str(message.from_user.id))
    webapp_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📱 Открыть кабинет",
            web_app=WebAppInfo(url="https://leviathanstory.ru/diet/app")
        )
    ]])
    tg_kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="✏️ Настроить через бот")],
        [KeyboardButton(text="🍝 Рецепт дня: вкл/выкл")],
        [KeyboardButton(text="❌ Закрыть")],
    ], resize_keyboard=True)
    await message.answer(
        _profile_text(p) if p else "👤 <b>Кабинет</b>\n\nПрофиль не заполнен.",
        parse_mode="HTML", reply_markup=tg_kb)
    await message.answer("📱 Или открой в браузере:", reply_markup=webapp_kb)


@router.message(F.text == "✏️ Настроить через бот")
async def start_cabinet(message: Message, state: FSMContext):
    await state.set_state(CabinetStates.level)
    await message.answer(
        "🍳 <b>Какой твой уровень кулинарии?</b>\n"
        "🥚 Новичок — яичница, пельмени, макароны\n"
        "🍳 Любитель — омлет, суп, паста болоньезе\n"
        "👨‍🍳 Готовлю — маринады, запеканка, соусы\n"
        "🌟 Эксперт — равиоли, ризотто, профи техники",
        parse_mode="HTML", reply_markup=_kb(list(LEVELS.keys()))
    )


@router.message(CabinetStates.level, F.text.in_(list(LEVELS.keys())))
async def got_level(message: Message, state: FSMContext):
    await state.update_data(cook_level=LEVELS[message.text])
    await state.set_state(CabinetStates.experiment)
    await message.answer(
        "🚀 <b>Отношение к новым рецептам?</b>",
        parse_mode="HTML", reply_markup=_kb(list(EXPS.keys()))
    )


@router.message(CabinetStates.experiment, F.text.in_(list(EXPS.keys())))
async def got_experiment(message: Message, state: FSMContext):
    await state.update_data(experiment_level=EXPS[message.text])
    await state.set_state(CabinetStates.budget)
    await message.answer(
        "💰 <b>Бюджет на еду?</b>\n"
        "🎓 Студенческий — чётко и без пармезана\n"
        "💰 Обычный — супермаркет без излишеств\n"
        "💳 Не считаю — можно любые продукты",
        parse_mode="HTML", reply_markup=_kb(list(BUDGETS.keys()))
    )


@router.message(CabinetStates.budget, F.text.in_(list(BUDGETS.keys())))
async def got_budget(message: Message, state: FSMContext):
    await state.update_data(budget_level=BUDGETS[message.text])
    await state.set_state(CabinetStates.time)
    await message.answer(
        "⏱ <b>Сколько времени на готовку?</b>",
        parse_mode="HTML", reply_markup=_kb(list(TIMES.keys()))
    )


@router.message(CabinetStates.time, F.text.in_(list(TIMES.keys())))
async def got_time(message: Message, state: FSMContext):
    await state.update_data(max_cook_time=TIMES[message.text])
    await state.set_state(CabinetStates.exclude)
    await message.answer(
        "🚫 <b>Есть продукты которые не ешь?</b>\n"
        "Напиши через запятую или «нет»:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="нет")],
            [KeyboardButton(text="❌ Отмена")]
        ], resize_keyboard=True)
    )


@router.message(CabinetStates.exclude)
async def got_exclude(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено", reply_markup=_main_kb())
    excl = "" if message.text.lower() == "нет" else message.text.strip()
    await state.update_data(excluded_foods=excl)
    await state.set_state(CabinetStates.recipe_day_time)
    await message.answer(
        "🍝 <b>Рецепт дня</b> — в какое время присылать?\n"
        "Напиши время форматом <code>10:00</code> или «не нужно»:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="09:00"), KeyboardButton(text="12:00")],
            [KeyboardButton(text="18:00"), KeyboardButton(text="не нужно")],
        ], resize_keyboard=True)
    )


@router.message(CabinetStates.recipe_day_time)
async def got_recipe_day_time(message: Message, state: FSMContext):
    import re
    text = message.text.strip()
    if text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено", reply_markup=_main_kb())
    rdt = None
    enabled = 0
    if text != "не нужно":
        t = text.replace(".", ":")
        if re.match(r'^([01]?\d|2[0-3]):[0-5]\d$', t):
            h, m = t.split(":")
            rdt = f"{int(h):02d}:{int(m):02d}"
            enabled = 1
        else:
            return await message.answer("Формат: <code>10:00</code> или «не нужно»", parse_mode="HTML")

    data = await state.get_data()
    await state.clear()
    tg_id = str(message.from_user.id)

    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute(
            "INSERT INTO user_profiles (tg_id,cook_level,experiment_level,budget_level,"
            "max_cook_time,excluded_foods,recipe_day_time,recipe_day_enabled) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(tg_id) DO UPDATE SET "
            "cook_level=excluded.cook_level, experiment_level=excluded.experiment_level,"
            "budget_level=excluded.budget_level, max_cook_time=excluded.max_cook_time,"
            "excluded_foods=excluded.excluded_foods, recipe_day_time=excluded.recipe_day_time,"
            "recipe_day_enabled=excluded.recipe_day_enabled",
            (tg_id,
             data.get("cook_level", "beginner"),
             data.get("experiment_level", "sometimes"),
             data.get("budget_level", "normal"),
             data.get("max_cook_time", 30),
             data.get("excluded_foods", ""),
             rdt, enabled)
        )
        await db.commit()

    # Перепланируем recipe_day job
    if enabled and rdt:
        from modules.scheduler.meal_scheduler import scheduler
        from apscheduler.triggers.cron import CronTrigger
        from modules.notifier.sender import send_notification
        from modules.recipes.engine import generate_recipe
        from modules.recipes.prompt_builder import build_random_recipe_prompt
        import asyncio, json

        async def send_recipe_day(uid=tg_id):
            async with aiosqlite.connect(DB_PATH, timeout=30) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM user_profiles WHERE tg_id=?", (uid,)) as c:
                    prof = dict(await c.fetchone() or {})
            if not prof.get("notify_personal", 1) or not prof.get("notify_recipe_day", 1):
                return
            from modules.puhlyash.persona import generate_puhlyash_recipe, format_puhlyash_message
            recipe = await generate_puhlyash_recipe(profile=prof)
            text = format_puhlyash_message(recipe)
            await send_notification(int(uid), text)

        job_id = f"recipe_day_{tg_id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        h, m = rdt.split(":")
        scheduler.add_job(send_recipe_day, CronTrigger(hour=int(h), minute=int(m)),
                          id=job_id, replace_existing=True)

    p = await _get_profile(tg_id)
    await message.answer(
        "✅ <b>Профиль сохранён!</b>\n\n" + _profile_text(p),
        parse_mode="HTML", reply_markup=_main_kb()
    )


@router.message(F.text == "🍝 Рецепт дня: вкл/выкл")
async def toggle_recipe_day(message: Message):
    tg_id = str(message.from_user.id)
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        async with db.execute(
            "SELECT recipe_day_enabled FROM user_profiles WHERE tg_id=?", (tg_id,)
        ) as c:
            row = await c.fetchone()
        cur = (row[0] if row else 0) or 0
        new = 1 - cur
        await db.execute(
            "UPDATE user_profiles SET recipe_day_enabled=? WHERE tg_id=?", (new, tg_id)
        )
        await db.commit()
    status = "✅ включён" if new else "❌ выключен"
    await message.answer(f"🍝 Рецепт дня: {status}", reply_markup=_main_kb())


@router.message(F.text == "❌ Закрыть")
async def close_cabinet(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню", reply_markup=_main_kb())