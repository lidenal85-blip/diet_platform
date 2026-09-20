"""Bot handler: Подбор диеты — опросник + Gemini рекомендации."""
import asyncio, json, sys
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
import planner

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
    """C-3.1: единый источник — bot_handlers.keyboards (compat-shim, имя сохранено)."""
    from bot_handlers.keyboards import main_kb
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


# ── Генерация diet-объектов (функции, вызывавшиеся из хендлеров, но не существовавшие) ──

def _extract_json(raw: str):
    """Достать JSON из ответа LLM: терпимо к ```-fence, префиксу и мусору вокруг."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    text = text.strip()
    start = text.find("[")
    alt = text.find("{")
    if alt != -1 and (start == -1 or alt < start):
        start = alt
    if start == -1:
        return None
    end = max(text.rfind("]"), text.rfind("}"))
    if end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None


DIET_JSON_RULE = (
    "Верни строго JSON-массив из 3 объектов, без текста вне JSON. "
    "Никаких фигурных скобок в тексте полей. Схема каждого объекта: "
    "name, tagline, calories_range, duration_weeks, difficulty, "
    "pros (массив 3 строк), cons (массив 2 строк), key_foods (массив 5-7 строк)."
)


def _heuristic_diets(data: dict) -> list:
    """Фоллбэк без LLM: 3 безопасных варианта по цели (CircuitBreaker/лимиты API)."""
    goal = str(data.get("goal", ""))
    if "Похудеть" in goal:
        base = [
            dict(name="Умеренный дефицит", tagline="Спокойное снижение веса без голода",
                 calories_range="1600–1900 ккал", duration_weeks=8, difficulty="лёгкая",
                 pros=["Нет жёстких ограничений", "Сохраняет мышцы", "Устойчивый результат"],
                 cons=["Медленный темп", "Нужен подсчёт калорий"],
                 key_foods=["курица", "рыба", "творог", "овощи", "гречка", "яйца"]),
            dict(name="Низкоуглеводная лёгкая", tagline="Меньше быстрых углеводов — меньше скачков аппетита",
                 calories_range="1500–1800 ккал", duration_weeks=6, difficulty="средняя",
                 pros=["Быстрое насыщение", "Минимум сладкого"],
                 cons=["Первая неделя — адаптация", "Может быть слабость"],
                 key_foods=["яйца", "мясо", "авокадо", "сыр", "зелень", "орехи"]),
            dict(name="Овощной дефицит", tagline="Больше объёма еды за те же калории",
                 calories_range="1500–1800 ккал", duration_weeks=6, difficulty="лёгкая",
                 pros=["Много еды по объёму", "Много клетчатки"],
                 cons=["Нужна готовка", "Не всем подходит по ЖКТ"],
                 key_foods=["овощи", "капуста", "кабачки", "грибы", "зелень", "индейка"]),
        ]
    elif "Набрать" in goal:
        base = [
            dict(name="Профицит + белок", tagline="Классический набор массы без жирового привеса",
                 calories_range="2600–3000 ккал", duration_weeks=10, difficulty="средняя",
                 pros=["Простой расчёт", "Хорошо сочетается с тренировками"],
                 cons=["Нужно есть по расписанию", "Дорого по продуктам"],
                 key_foods=["говядина", "рис", "творог", "орехи", "бананы", "яйца"]),
            dict(name="Углеводное окно", tagline="Углеводы вокруг тренировок",
                 calories_range="2700–3100 ккал", duration_weeks=10, difficulty="средняя",
                 pros=["Энергия на тренировки", "Быстрое восстановление"],
                 cons=["Привязка к расписанию", "Не для малоподвижных"],
                 key_foods=["рис", "макароны", "картофель", "курица", "хлеб", "мёд"]),
            dict(name="Молочный набор", tagline="Максимум калорий из жидких и молочных продуктов",
                 calories_range="2800–3200 ккал", duration_weeks=8, difficulty="лёгкая",
                 pros=["Готовится быстро", "Удобно пить в дороге"],
                 cons=["Не подходит при непереносимости лактозы", "Приедается"],
                 key_foods=["молоко", "творог", "сметана", "кефир", "овсянка", "арахисовая паста"]),
        ]
    else:
        base = [
            dict(name="Сбалансированная тарелка", tagline="БЖУ 30-30-40 без фанатизма",
                 calories_range="1900–2300 ккал", duration_weeks=8, difficulty="лёгкая",
                 pros=["Ничего не запрещено", "Легко держаться долго"],
                 cons=["Медленная динамика", "Нужен базовый контроль порций"],
                 key_foods=["крупы", "рыба", "овощи", "фрукты", "мясо", "молочные"]),
            dict(name="Средиземноморская", tagline="Золотой стандарт здорового питания",
                 calories_range="1900–2300 ккал", duration_weeks=12, difficulty="лёгкая",
                 pros=["Максимум научных данных", "Разнообразная еда"],
                 cons=["Рыба может быть дорогой", "Нужно привыкнуть к оливковому маслу"],
                 key_foods=["рыба", "оливковое масло", "овощи", "орехи", "бобовые", "цельнозерновой хлеб"]),
            dict(name="Рацион 16+8", tagline="Интервальное питание без подсчёта калорий",
                 calories_range="1900–2200 ккал", duration_weeks=8, difficulty="средняя",
                 pros=["Не надо считать ккал", "Простое правило"],
                 cons=["Нельзя при гастрите/диабете без врача", "Голод вечером в начале"],
                 key_foods=["яйца", "мясо", "крупы", "овощи", "супы", "йогурт"]),
        ]
    return base


async def _get_3_diets(data: dict) -> list:
    """3 варианта диеты по профилю. LLM → при сбое эвристика (пользователь не видит ошибку)."""
    goal = str(data.get("goal", ""))
    age = data.get("age", "")
    restrictions = str(data.get("restrictions", ""))
    activity = str(data.get("activity", ""))
    restrictions_note = f" Учитывай ограничения: {restrictions}." if restrictions and "Нет ограничений" not in restrictions else ""
    prompt = (
        f"Подбери 3 варианта диеты. Цель: {goal}. Возраст: {age}. "
        f"Активность: {activity}.{restrictions_note} " + DIET_JSON_RULE
    )
    if _LEV:
        try:
            raw = await asyncio.wait_for(_gemini(prompt), timeout=45)
            parsed = _extract_json(raw)
            if isinstance(parsed, list) and len(parsed) >= 3 and all(isinstance(d, dict) and d.get("name") for d in parsed[:3]):
                return parsed[:3]
        except Exception as e:
            log.warning("diet picker: LLM недоступен, эвристика ( %s )", e)
    return _heuristic_diets(data)


def _heuristic_week_plan(diet_name: str, data: dict) -> dict:
    """Фоллбэк-план недели без LLM: базовые приёмы на каждый день."""
    days = []
    for day in ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]:
        days.append(dict(
            day=day,
            breakfast=dict(название="Овсянка с фруктами и орехами", ккал="400"),
            lunch=dict(название="Куриная грудка с гречкой и овощами", ккал="600"),
            dinner=dict(название="Творог с зеленью и овощной салат", ккал="350"),
            snack="Яблоко и горсть орехов",
        ))
    return dict(
        days=days,
        shopping_list=["овсянка 1 кг", "фрукты 2 кг", "куриная грудка 2 кг", "гречка 1 кг",
                       "овощи 3 кг", "творог 1.5 кг", "зелень", "орехи 300 г", "яблоки 1 кг"],
        tips=["Пей 1.5–2 литра воды в день.", "Последний приём пищи — за 2–3 часа до сна.",
              f"Диета «{diet_name}» — это ориентир: слушай свой организм."],
    )


async def _get_week_plan(diet_name: str, data: dict) -> dict:
    """План питания на неделю для выбранной диеты. LLM → при сбое эвристика."""
    prompt = (
        f"Составь план питания на 7 дней для диеты: {diet_name}. Все тексты строго на русском языке (и названия дней недели тоже). "
        "Верни строго JSON без текста вне JSON и без фигурных скобок внутри текста полей. "
        "Ключи верхнего уровня строго латиницей: days, shopping_list, tips. "
        "days — массив из 7 объектов с ключами day, breakfast, lunch, dinner (опционально snack); "
        "каждый приём — объект с ключами название и ккал. "
        "shopping_list — массив строк, tips — массив 2-3 строк."
    )
    if _LEV:
        try:
            raw = await asyncio.wait_for(_gemini(prompt), timeout=45)
            parsed = _extract_json(raw)
            if isinstance(parsed, dict) and isinstance(parsed.get("days"), list) and len(parsed["days"]) >= 5:
                return parsed
        except Exception as e:
            log.warning("week plan: LLM недоступен, эвристика ( %s )", e)
    return _heuristic_week_plan(diet_name, data)


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
            snack = day["snack"]
            if isinstance(snack, dict):
                sname = snack.get("название") or snack.get("name") or ""
                kcal = snack.get("ккал") or snack.get("kcal") or "?"
                snack = f"{sname} ({kcal} ккал)" if sname else str(snack)
            lines.append(f"  🍎 Перекус: {snack}")
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
    # §20-7: старт онбординга — own-try: сбой аналитики не ломает пользовательский флоу
    try:
        async with aiosqlite.connect(DB_PATH, timeout=30) as ev_db:
            await planner.log_event(ev_db, "onboarding_started", str(message.from_user.id))
            await ev_db.commit()
    except Exception as e:  # noqa: BLE001
        log.error("onboarding_started event failed: %s", e)
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

    # Сохраняем профиль в БД (§10 single-writer: ЕДИНСТВЕННЫЙ upsert профиля;
    # §20-3: restrictions/activity теперь тоже сохраняются, а не живут только в FSM)
    tg_id = str(message.from_user.id)
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute(
            "INSERT INTO user_profiles (tg_id, goal, age, restrictions, activity, onboarding_done) "
            "VALUES (?,?,?,?,?,1) "
            "ON CONFLICT(tg_id) DO UPDATE SET goal=excluded.goal, age=excluded.age, "
            "restrictions=excluded.restrictions, activity=excluded.activity, onboarding_done=1",
            (tg_id, data.get("goal", ""), data.get("age", 0),
             data.get("restrictions", ""), data.get("activity", ""))
        )
        await db.commit()
        # §20-7: onboarding_completed — строго ПОСЛЕ commit профиля; сбой
        # аналитики не ломает флоу и не откатывает upsert (own-try контракт)
        try:
            await planner.log_event(db, "onboarding_completed", tg_id,
                                    {"goal": data.get("goal", "")})
            await db.commit()
        except Exception as e:  # noqa: BLE001
            log.error("onboarding_completed event failed: %s", e)

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

        # §20-3 / PATCH-5: LLM вне транзакции — здесь план уже сгенерирован и
        # показывается пользователю; атомарная запись program+plan+meal_state+
        # events (PATCH-4: meal_state только по фактическим слотам).
        try:
            async with aiosqlite.connect(DB_PATH, timeout=30) as db:
                db.row_factory = aiosqlite.Row
                await planner.persist_plan_bundle(
                    db,
                    tg_id=tg_id,
                    diet_name=diet_name,
                    source="diet_picker",
                    card=chosen,
                    constraints={
                        "goal": data.get("goal", ""),
                        "age": data.get("age", 0),
                        "restrictions": data.get("restrictions", ""),
                        "activity": data.get("activity", ""),
                    },
                    days=plan.get("days", []),
                    shopping_list=plan.get("shopping_list") or [],
                    tips=plan.get("tips") or [],
                    # §20-7: plan_viewed атомарно с bundle (пользователь увидел план)
                    extra_events=[
                        ("plan_viewed", {"diet_name": diet_name}),
                    ],
                )
        except planner.SlotsError as e:
            # план пользователю уже отправлен; запись в домен — громкий отказ в лог
            log.error("plan bundle persist failed: %s", e)

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