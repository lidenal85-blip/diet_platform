"""Bot handlers v2: Рецепты, Холодильник, Бюджет, Шеф на телефоне."""
import json, sys
import aiosqlite
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from building_blocks.logger import get_logger
from database import DB_PATH
from modules.recipes.engine import generate_recipe, generate_from_fridge, generate_budget_recipe, MODES

log = get_logger(__name__)
router = Router()

sys.path.insert(0, "/opt/leviathan_engine")
try:
    from llm_factory import LLMFactory
    _LEVIATHAN_CORE = True
except ImportError:
    _LEVIATHAN_CORE = False
    log.warning("⚠️ LLMFactory недоступен в recipes.py, Чеф на телефоне не будет работать")


async def _ask_llm(prompt: str, system: str) -> str:
    """Свободный чат («Шеф на телефоне») через Leviathan LLMFactory:
    KeyPool + CircuitBreaker + fallback на Groq, вместо raw urllib + ручной ротации ключей.
    """
    if not _LEVIATHAN_CORE:
        raise RuntimeError("LLMFactory недоступен")
    return await LLMFactory.execute_request(
        prompt=prompt,
        system=system,
        model="gemini-2.5-flash",
        driver="gemini",
        fallback=True,
        task_type="default",
    )


class RecipeStates(StatesGroup):
    waiting_query = State()
    waiting_mode = State()

class FridgeStates(StatesGroup):
    waiting_ingredients = State()

class BudgetStates(StatesGroup):
    waiting_amount = State()

class ChefStates(StatesGroup):
    chatting = State()


MODE_MAP = {"⚡ Быстро": "quick", "🏠 Домашний": "home",
            "🍽 Ресторанный": "restaurant", "🥦 ПП": "pp"}


def recipes_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="⚡ Быстро"), KeyboardButton(text="🏠 Домашний")],
        [KeyboardButton(text="🍽 Ресторанный"), KeyboardButton(text="🥦 ПП")],
        [KeyboardButton(text="🔙 Назад")],
    ], resize_keyboard=True)


def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎯 Подобрать диету"), KeyboardButton(text="👤 Кабинет")],
        [KeyboardButton(text="🍝 Рецепт от Пухляша"), KeyboardButton(text="👨‍🍳 Рецепты")],
        [KeyboardButton(text="🧊 Холодильник"), KeyboardButton(text="💰 По бюджету")],
        [KeyboardButton(text="👨‍🍳 Шеф на телефоне"), KeyboardButton(text="⏰ Расписание")],
        [KeyboardButton(text="🐈 Пухляш"), KeyboardButton(text="ℹ️ Помощь")],
    ], resize_keyboard=True, persistent=True)


def _fmt(r: dict) -> str:
    ingr = json.loads(r.get("ingredients", "[]"))
    steps = json.loads(r.get("steps", "[]"))
    tags = json.loads(r.get("tags", "[]"))
    lines = [
        f"🍳 <b>{r.get('title','?')}</b>",
        f"📝 {r.get('description','')}", "",
        f"⏱ {r.get('cook_time_minutes','?')} мин  |  👤 {r.get('servings',2)} порции",
        f"🔥 {r.get('calories_per_serving','?')} ккал  |"
        f"  Б:{r.get('protein_g','?')}г  Ж:{r.get('fat_g','?')}г  У:{r.get('carbs_g','?')}г",
        "", "<b>Ингредиенты:</b>"
    ] + [f"• {i}" for i in ingr] + ["", "<b>Приготовление:</b>"] + list(steps)
    if tags:
        lines += ["", "🏷 " + "  ".join(f"#{t}" for t in tags)]
    return "\n".join(lines)


async def _save(recipe: dict):
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute(
            "INSERT OR IGNORE INTO recipes "
            "(id,title,mode,description,ingredients,steps,"
            "calories_per_serving,protein_g,fat_g,carbs_g,cook_time_minutes,servings,tags)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (recipe["id"], recipe.get("title",""), recipe.get("mode",""),
             recipe.get("description",""), recipe["ingredients"], recipe["steps"],
             recipe.get("calories_per_serving"), recipe.get("protein_g"),
             recipe.get("fat_g"), recipe.get("carbs_g"),
             recipe.get("cook_time_minutes"), recipe.get("servings", 2), recipe["tags"])
        )
        await db.commit()


# ── Рецепты ───────────────────────────────────────────────
@router.message(F.text == "👨‍🍳 Рецепты")
async def btn_recipes(message: Message, state: FSMContext):
    log.info("btn_recipes called from %s", message.from_user.id)
    await state.set_state(RecipeStates.waiting_query)
    await message.answer(
        "👨‍🍳 <b>Рецепты</b>\n\nЧто хочешь приготовить?\nНапример: <code>паста карбонара</code>",
        parse_mode="HTML", reply_markup=recipes_kb()
    )


@router.message(RecipeStates.waiting_query, F.text.in_(list(MODE_MAP.keys())))
async def recipe_query_is_mode(message: Message, state: FSMContext):
    """User сразу выбрал режим без запроса — генерируем случайное блюдо."""
    mode = MODE_MAP[message.text]
    await state.clear()
    RANDOM_QUERIES = {
        "quick": "быстрый завтрак",
        "home": "вкусный ужин",
        "restaurant": "ресторанное блюдо",
        "pp": "здоровое блюдо",
    }
    query = RANDOM_QUERIES.get(mode, "вкусное блюдо")
    msg = await message.answer("⏳ Генерирую рецепт…", reply_markup=main_kb())
    try:
        import asyncio
        recipe = await asyncio.wait_for(generate_recipe(query, mode), timeout=45)
        await _save(recipe)
        await msg.delete()
        from modules.reactions.engine import reaction_kb as _rkb
        rid = recipe.get("id", "")
        await message.answer(_fmt(recipe), parse_mode="HTML",
            reply_markup=_rkb("recipe", rid) if rid else main_kb())
        if rid:
            await message.answer("👇 Как тебе?", reply_markup=main_kb())
    except asyncio.TimeoutError:
        await message.answer("❌ Генерация заняла слишком долго. Попробуй ещё раз.")
    except Exception as e:
        log.error("recipe: %s", e)
        await message.answer(f"❌ Ошибка: {e}")


@router.message(RecipeStates.waiting_query,
    F.text.not_in(list(MODE_MAP.keys()) + ["🔙 Назад"]))
async def recipe_got_query(message: Message, state: FSMContext):
    await state.update_data(query=message.text.strip())
    await state.set_state(RecipeStates.waiting_mode)
    await message.answer(
        f"🍽 <b>{message.text.strip()}</b>\n\nВыбери режим:",
        parse_mode="HTML", reply_markup=recipes_kb()
    )


@router.message(RecipeStates.waiting_mode, F.text.in_(list(MODE_MAP.keys())))
async def recipe_got_mode(message: Message, state: FSMContext):
    data = await state.get_data()
    mode = MODE_MAP[message.text]
    query = data.get("query", "вкусное блюдо")
    await state.clear()
    msg = await message.answer("⏳ Генерирую рецепт…", reply_markup=main_kb())
    try:
        import asyncio
        recipe = await asyncio.wait_for(generate_recipe(query, mode), timeout=45)
        await _save(recipe)
        await msg.delete()
        from modules.reactions.engine import reaction_kb as _rkb
        rid = recipe.get("id", "")
        await message.answer(_fmt(recipe), parse_mode="HTML",
            reply_markup=_rkb("recipe", rid) if rid else main_kb())
        if rid:
            await message.answer("👇 Как тебе?", reply_markup=main_kb())
    except asyncio.TimeoutError:
        await message.answer("❌ Генерация заняла слишком долго. Попробуй ещё раз.")
    except Exception as e:
        log.error("recipe: %s", e)
        await message.answer(f"❌ Ошибка: {e}")


# ── Холодильник ──────────────────────────────────────────
@router.message(F.text == "🧊 Холодильник")
async def btn_fridge(message: Message, state: FSMContext):
    await state.set_state(FridgeStates.waiting_ingredients)
    await message.answer(
        "🧊 <b>Холодильник</b>\n\nПеречисли что есть через запятую:\n"
        "<code>курица, яйца, помидоры, сыр</code>",
        parse_mode="HTML"
    )


@router.message(FridgeStates.waiting_ingredients)
async def fridge_got_ingredients(message: Message, state: FSMContext):
    ingredients = [i.strip() for i in message.text.split(",") if i.strip()]
    if len(ingredients) < 2:
        await message.answer("Укажи хотя бы 2 ингредиента через запятую")
        return
    await state.clear()
    msg = await message.answer(f"🧨 Смотрю что сделать из {len(ingredients)} продуктов…", reply_markup=main_kb())
    try:
        import asyncio
        recipe = await asyncio.wait_for(generate_from_fridge(ingredients), timeout=45)
        await _save(recipe)
        await msg.delete()
        from modules.reactions.engine import reaction_kb as _rkb
        rid = recipe.get("id", "")
        await message.answer(_fmt(recipe), parse_mode="HTML",
            reply_markup=_rkb("recipe", rid) if rid else main_kb())
        if rid:
            await message.answer("👇 Как тебе?", reply_markup=main_kb())
    except asyncio.TimeoutError:
        await message.answer("❌ Генерация заняла слишком долго. Попробуй ещё раз.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


# ── По бюджету ───────────────────────────────────────────
@router.message(F.text == "💰 По бюджету")
async def btn_budget(message: Message, state: FSMContext):
    await state.set_state(BudgetStates.waiting_amount)
    await message.answer(
        "💰 <b>Меню по бюджету</b>\n\nНапиши сумму в рублях:\n<code>500</code>",
        parse_mode="HTML"
    )


@router.message(BudgetStates.waiting_amount)
async def budget_got_amount(message: Message, state: FSMContext):
    digits = "".join(filter(str.isdigit, message.text or ""))
    if not digits:
        await message.answer("Напиши число, например: <code>500</code>", parse_mode="HTML")
        return
    budget = int(digits)
    await state.clear()
    msg = await message.answer(f"💰 Придумываю ужин на {budget} руб…", reply_markup=main_kb())
    try:
        import asyncio
        recipe = await asyncio.wait_for(generate_budget_recipe(budget), timeout=45)
        await _save(recipe)
        await msg.delete()
        from modules.reactions.engine import reaction_kb as _rkb
        rid = recipe.get("id", "")
        await message.answer(_fmt(recipe), parse_mode="HTML",
            reply_markup=_rkb("recipe", rid) if rid else main_kb())
        if rid:
            await message.answer("👇 Как тебе?", reply_markup=main_kb())
    except asyncio.TimeoutError:
        await message.answer("❌ Генерация заняла слишком долго. Попробуй ещё раз.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


# ── Шеф на телефоне ───────────────────────────────────
@router.message(F.text == "👨‍🍳 Шеф на телефоне")
async def btn_chef(message: Message, state: FSMContext):
    await state.set_state(ChefStates.chatting)
    await state.update_data(history=[])
    await message.answer(
        "👨‍🍳 <b>Шеф на телефоне</b>\n\nСпрашивай что угодно:\n"
        "• Как пожарить стейк?\n• Чем заменить яйца?\n• Сколько варить пасту?\n\n"
        "Для выхода напиши <code>стоп</code>",
        parse_mode="HTML"
    )


@router.message(ChefStates.chatting)
async def chef_chat(message: Message, state: FSMContext):
    if message.text and message.text.lower().strip() in ("стоп", "stop", "выход", "🔙 назад"):
        await state.clear()
        await message.answer("👍 До следующего раза!", reply_markup=main_kb())
        return
    data = await state.get_data()
    history = data.get("history", [])
    msg = await message.answer("👨‍🍳 Думаю…")
    try:
        sys_chef = "Ты опытный шеф-повар. Отвечай кратко, практично, по делу. На русском."
        history.append({"role": "user", "text": message.text})
        # LLMFactory не принимает multi-turn contents напрямую — сворачиваем
        # историю в один промпт (последние 10 реплик)
        dialogue = "\n".join(
            f"{'Пользователь' if h['role']=='user' else 'Шеф'}: {h['text']}"
            for h in history[-10:]
        )
        answer = await _ask_llm(prompt=dialogue, system=sys_chef)
        history.append({"role": "model", "text": answer})
        await state.update_data(history=history[-20:])
        await msg.delete()
        await message.answer(f"👨‍🍳 {answer}")
    except Exception as e:
        log.error("chef_chat: %s", e)
        try:
            await msg.delete()
        except Exception:
            pass
        await message.answer("❌ Шеф сейчас занят, попробуй позже")


# ── Назад ────────────────────────────────────────────────
# ── Рецепт от Пухляша ──────────────────────────────────────

@router.message(F.text == "🍝 Рецепт от Пухляша")
async def btn_puhlyash_recipe(message: Message, state: FSMContext):
    import asyncio
    import aiosqlite
    from database import DB_PATH
    from modules.puhlyash.persona import generate_puhlyash_recipe, format_puhlyash_message
    msg = await message.answer("🍝 Пухляш думает...", reply_markup=main_kb())
    try:
        tg_id = str(message.from_user.id)
        profile = {}
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM user_profiles WHERE tg_id=?", (tg_id,)) as c:
                row = await c.fetchone()
            if row:
                profile = dict(row)
        recipe = await asyncio.wait_for(
            generate_puhlyash_recipe(profile=profile), timeout=45
        )
        text = format_puhlyash_message(recipe)
        await msg.delete()
        from modules.reactions.engine import reaction_kb
        rid = recipe.get("id", "")
        await _save(recipe)
        await message.answer(text, parse_mode="HTML",
                             reply_markup=reaction_kb("recipe", rid) if rid else main_kb())
        if rid:
            await message.answer("👇 Как тебе?", reply_markup=main_kb())
    except asyncio.TimeoutError:
        await message.answer("❌ Пухляш задумался... Попробуй ещё раз!")
    except Exception as e:
        log.error("puhlyash recipe: %s", e)
        await message.answer(f"❌ {e}")


@router.message(F.text == "🔙 Назад")
async def btn_back(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню", reply_markup=main_kb())