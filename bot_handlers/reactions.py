"""Callback handler: реакции на рецепты/диеты/упражнения."""
import asyncio
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from building_blocks.logger import get_logger
from modules.reactions.engine import save_reaction, reaction_kb_with_reason

log = get_logger(__name__)
router = Router()


class WizardStates(StatesGroup):
    chatting = State()


@router.callback_query(F.data.startswith("react:"))
async def on_reaction(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":", 3)
    if len(parts) < 4:
        return await call.answer()
    _, reaction, item_type, item_id = parts
    tg_id = str(call.from_user.id)

    item_title = ""
    if call.message and call.message.html_text:
        for line in call.message.html_text.split("\n"):
            clean = line.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "").strip()
            if clean and not clean.startswith("\u2022") and not clean.startswith("\u23f1"):
                item_title = clean[:80]
                break

    if reaction == "save":
        await save_reaction(tg_id, item_type, item_id, item_title, "save")
        return await call.answer("🔖 Сохранено!", show_alert=False)

    if reaction in ("like", "dislike"):
        await save_reaction(tg_id, item_type, item_id, item_title, reaction)
        emoji = "👍" if reaction == "like" else "👎"
        await call.answer(f"{emoji} Записал!", show_alert=False)
        kb = reaction_kb_with_reason(item_type, item_id, reaction)
        await call.message.answer(
            f"{'\u0420ад слышать! ' if reaction == 'like' else '\u0416аль... '}"
            f"Хочешь уточнить почему? (\u043dеобязательно)",
            reply_markup=kb
        )
        return

    if reaction == "alt":
        await call.answer("🔄 Генерирую альтернативы...", show_alert=False)
        await _send_alternatives(call, item_id, tg_id)
        return

    if reaction == "expand":
        await call.answer("💡 Запускаю мастера...", show_alert=False)
        await _start_wizard(call, item_id, item_title, state)
        return


@router.callback_query(F.data.startswith("reason:"))
async def on_reason(call: CallbackQuery):
    parts = call.data.split(":", 3)
    if len(parts) < 4:
        return await call.answer()
    _, reason, item_type, item_id = parts
    tg_id = str(call.from_user.id)
    if reason != "skip":
        import aiosqlite
        from database import DB_PATH
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            await db.execute(
                "UPDATE reactions SET reason=? WHERE tg_id=? AND item_type=? AND item_id=? "
                "ORDER BY created_at DESC LIMIT 1",
                (reason, tg_id, item_type, item_id)
            )
            await db.commit()
    await call.answer("✅ Спасибо!", show_alert=False)
    try:
        await call.message.delete()
    except Exception:
        pass


async def _send_alternatives(call: CallbackQuery, item_id: str, tg_id: str):
    import aiosqlite
    from database import DB_PATH
    from modules.recipes.engine import generate_recipe
    from modules.reactions.engine import reaction_kb

    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT title, mode FROM recipes WHERE id=?", (item_id,)) as c:
            row = await c.fetchone()

    title = row["title"] if row else "блюдо"
    mode = row["mode"] if row else "home"
    msg = await call.message.answer(f"🔄 Придумываю альтернативы к «{title}»...")
    try:
        from bot_handlers.recipes import _fmt, _save
        alt1, alt2 = await asyncio.gather(
            generate_recipe(f"простой вариант похожего на {title}", mode),
            generate_recipe(f"необычный вариант блюда похожего на {title}", mode),
        )
        await _save(alt1)
        await _save(alt2)
        await msg.delete()
        await call.message.answer(f"🔄 <b>Альтернативы к «{title}»:</b>", parse_mode="HTML")
        await call.message.answer(f"1️⃣ <b>Попроще:</b>\n\n{_fmt(alt1)}", parse_mode="HTML",
                                   reply_markup=reaction_kb("recipe", alt1["id"]))
        await call.message.answer(f"2️⃣ <b>Поинтереснее:</b>\n\n{_fmt(alt2)}", parse_mode="HTML",
                                   reply_markup=reaction_kb("recipe", alt2["id"]))
    except Exception as e:
        log.error("alternatives: %s", e)
        await msg.edit_text(f"❌ Ошибка: {e}")


async def _start_wizard(call: CallbackQuery, item_id: str, item_title: str, state: FSMContext):
    await state.set_state(WizardStates.chatting)
    await state.update_data(wizard_recipe=item_title, wizard_history=[], wizard_item_id=item_id)
    await call.message.answer(
        f"🧑‍🍳 <b>Мастер кулинарных экспериментов</b>\n\n"
        f"Пухляш готов поэкспериментировать с <b>{item_title}</b>!\n\n"
        f"Что хочешь добавить или изменить?\n"
        f"Например: <i>добавить помидоры</i>, <i>сделать острее</i>, <i>без мяса</i>\n\n"
        f"<i>Но учти — Пухляш проверит можно ли такое сочетать 😄</i>\n\n"
        f"Для выхода напиши <code>стоп</code>",
        parse_mode="HTML"
    )


@router.message(WizardStates.chatting)
async def wizard_chat(message: Message, state: FSMContext):
    import re, random, urllib.request, json
    if message.text and message.text.lower().strip() in ("стоп", "stop", "выход", "хватит"):
        await state.clear()
        return await message.answer("👨‍🍳 Опыт закончен! Приятного аппетита 😋")

    data = await state.get_data()
    recipe_name = data.get("wizard_recipe", "блюдо")
    history = data.get("wizard_history", [])
    msg = await message.answer("🧐 Пухляш думает...")

    sys_prompt = (
        f"Ты Пухляш — опытный повар с характером. "
        f"Пользователь хочет экспериментировать с «{recipe_name}». "
        f"Твоя задача:\n"
        f"1. Проверить совместимость ингредиентов (как селёдка с молоком — плохая идея)\n"
        f"2. Если плохое сочетание — честно предупреди, с юмором\n"
        f"3. Если нормальное — подскажи как добавить\n"
        f"4. Если отличное — восхитись и опиши что получится\n"
        f"Не соглашайся на всё. Быть контролирующим, но дружелюбным. Коротко (2-4 предложения). На русском."
    )

    history.append({"role": "user", "parts": [{"text": message.text}]})
    try:
        env = open("/opt/leviathan_engine/agent_service/.env").read()
        keys = re.findall(r'GEMINI_K\d+=([^\s]+)', env)
        random.shuffle(keys)
        for key in keys:
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   f"gemini-3.1-flash-lite:generateContent?key={key}")
            body = json.dumps({
                "system_instruction": {"parts": [{"text": sys_prompt}]},
                "contents": history[-8:],
                "generationConfig": {"temperature": 0.85, "maxOutputTokens": 350}
            }).encode()
            try:
                req = urllib.request.Request(url, body, {"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=25) as r:
                    answer = json.loads(r.read())["candidates"][0]["content"]["parts"][0]["text"]
                history.append({"role": "model", "parts": [{"text": answer}]})
                await state.update_data(wizard_history=history[-12:])
                await msg.delete()
                await message.answer(f"👨‍🍳 {answer}")
                return
            except Exception as e:
                if any(x in str(e) for x in ["403", "429", "503"]): continue
                raise
        await msg.edit_text("❌ Пухляш временно недоступен, попробуй позже")
    except Exception as e:
        await msg.edit_text(f"❌ {e}")