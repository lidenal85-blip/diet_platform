"""Telegram Bot — Delivery Layer «Пухляш» (aiogram3).

Постоянная клавиатура (ReplyKeyboard) + полный набор команд.
"""
import asyncio
from typing import Optional
import aiosqlite

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove, WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from building_blocks.config import get_settings
from building_blocks.contracts import new_trace_id
from building_blocks.logger import get_logger, set_trace_context
from database import DB_PATH
from modules.search_gateway.internal.searcher import initiate_search
from modules.diet_registry.infrastructure.repository import (
    get_diet_by_id, search_diets, verify_diet
)

log = get_logger(__name__)
cfg = get_settings()

router = Router()

# ── Постоянная нижняя клавиатура ───────────────────────────

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🎯 Подобрать диету"), KeyboardButton(text="👤 Кабинет")],
        [KeyboardButton(text="🍝 Рецепт от Пухляша"), KeyboardButton(text="👨‍🍳 Рецепты")],
        [KeyboardButton(text="🧊 Холодильник"), KeyboardButton(text="💰 По бюджету")],
        [KeyboardButton(text="👨‍🍳 Шеф на телефоне"), KeyboardButton(text="⏰ Расписание")],
        [KeyboardButton(text="ℹ️ Помощь")],
    ],
    resize_keyboard=True,
    persistent=True,
)


def _main_kb() -> ReplyKeyboardMarkup:
    return MAIN_KEYBOARD


# ── /start ───────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    webapp_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📱 Открыть кабинет",
            web_app=WebAppInfo(url=f"https://leviathanstory.ru/diet/app?uid={message.from_user.id}")
        )
    ]])
    await message.answer(
        "🍝 <b>Пухляш</b> — свой парень, накормит вкусно 😋\n\n"
        "🎯 <b>Что умею:</b>\n"
        "• Подберу диету под тебя\n"
        "• Предложу рецепты по твоему уровню\n"
        "• Напомню когда есть\n"
        "• Пришлю рецепт дня в личку\n\n"
        "⬇️ Нажми что хочешь или настрой профиль:",
        parse_mode="HTML",
        reply_markup=_main_kb(),
    )
    await message.answer(
        "📱 Настрой профиль в кабинете:",
        reply_markup=webapp_kb
    )
# ── /help ──────────────────────────────────────────────

@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message):
    await message.answer(
        "🔬 <b>Diet Platform — справка</b>\n\n"
        "Ищу диеты из интернета, извлекаю структуру, валидирую.\n\n"
        "<b>Поиск:</b>\n"
        "🔍 /search &lt;запрос&gt; — найти диету по ключевому слову\n\n"
        "<b>Просмотр:</b>\n"
        "🥗 /diets [&lt;запрос&gt;] — верифицированные диеты\n"
        "⏳ /pending — диеты на модерации\n"
        "🔍 /status &lt;id&gt; — статус запроса\n\n"
        "<b>Администрирование:</b>\n"
        "🚨 /dlq — Dead Letter Queue (ошибки)\n"
        "❤️ /health — здоровье сервиса",
        parse_mode="HTML",
        reply_markup=_main_kb(),
    )


# ── /health ────────────────────────────────────────────

@router.message(Command("health"))
async def cmd_health(message: Message):
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("http://127.0.0.1:8150/health", timeout=aiohttp.ClientTimeout(total=3)) as r:
                data = await r.json()
        await message.answer(
            f"❤️ <b>Сервис работает</b>\n"
            f"version: {data.get('version', '?')}\n"
            f"status: {data.get('status', '?')}",
            parse_mode="HTML",
        )
    except Exception as e:
        await message.answer(f"❌ Сервис недоступен: {e}", reply_markup=_main_kb())


# ── /search ──────────────────────────────────────────

@router.message(Command("search"))
@router.message(F.text == "🔍 Найти диету")
async def cmd_search(message: Message):
    parts = message.text.split(maxsplit=1) if message.text else []
    # Кнопка — просим ввести запрос
    if len(parts) < 2 or parts[0] == "🔍 Найти диету":
        await message.answer(
            "🔍 Напиши запрос через команду:\n"
            "<code>/search кето диета при диабете</code>\n\n"
            "Или просто напиши запрос следующим сообщением.",
            parse_mode="HTML",
        )
        return

    query = parts[1].strip()[:300]
    user_id = str(message.from_user.id)
    trace_id = new_trace_id()
    set_trace_context(trace_id)

    msg = await message.answer(f"🔍 Ищу: <b>{query}</b>\n\n…", parse_mode="HTML", reply_markup=_main_kb())

    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        session_id = await initiate_search(db, query, user_id)

    await msg.edit_text(
        f"🔍 Запрос запущен!\n"
        f"🆔 <code>{session_id}</code>\n\n"
        f"Проверь статус: /status {session_id[:8]}…\n"
        f"Или смотри диеты: /diets",
        parse_mode="HTML",
    )


# ── Текстовый ввод после кнопки "Найти диету" ───────────────

_awaiting_search: set[int] = set()   # user_id кто нажал кнопку


@router.message(F.text == "🔍 Найти диету")
async def btn_search_prompt(message: Message):
    _awaiting_search.add(message.from_user.id)
    await message.answer(
        "🔍 Напиши что ищем, например:\n"
        "<code>кето диета при диабете</code>",
        parse_mode="HTML",
    )


@router.message(F.func(lambda m: m.from_user.id in _awaiting_search))
async def handle_freetext_search(message: Message):
    if not message.text or len(message.text.strip()) < 2:
        await message.answer("Слишком короткий запрос")
        return
    _awaiting_search.discard(message.from_user.id)

    query = message.text.strip()[:300]
    user_id = str(message.from_user.id)
    trace_id = new_trace_id()
    set_trace_context(trace_id)

    msg = await message.answer(f"🔍 Ищу: <b>{query}</b>\n\n…", parse_mode="HTML", reply_markup=_main_kb())

    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        session_id = await initiate_search(db, query, user_id)

    await msg.edit_text(
        f"🔍 Запрос запущен!\n"
        f"🆔 <code>{session_id}</code>\n\n"
        f"Проверь статус: /status {session_id[:8]}…",
        parse_mode="HTML",
    )


# ── /status ──────────────────────────────────────────

@router.message(Command("status"))
async def cmd_status(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Укажи session_id: /status &lt;id&gt;", parse_mode="HTML", reply_markup=_main_kb())
        return

    session_id_part = parts[1].strip()
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM search_sessions WHERE id LIKE ?",
            (session_id_part + "%",)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        await message.answer("❌ Сессия не найдена")
        return

    status_emoji = {
        "completed": "✅", "failed": "❌", "searching": "🔍",
        "scraping": "🌐", "extracting": "🧠",
    }.get(row["status"], "⏳")

    await message.answer(
        f"{status_emoji} <b>Статус сессии</b>\n"
        f"📝 Запрос: {row['query_text']}\n"
        f"🟡 Статус: {row['status']}\n"
        f"🕒 {row['created_at']}",
        parse_mode="HTML",
    )


# ── /diets ───────────────────────────────────────────

@router.message(Command("diets"))
@router.message(F.text == "🥗 Мои диеты")
async def cmd_diets(message: Message):
    parts = message.text.split(maxsplit=1) if message.text else []
    query = ""
    if len(parts) > 1 and parts[0].startswith("/"):
        query = parts[1].strip()

    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        diets = await search_diets(db, query=query, status="approved", limit=8)

    if not diets:
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            db.row_factory = aiosqlite.Row
            diets = await search_diets(db, query=query,
                                       status="pending_verification", limit=8)
        if not diets:
            await message.answer(
                "💭 Диет пока нет.\n"
                "Используй /search для поиска."
            )
            return

    kb = InlineKeyboardBuilder()
    for d in diets:
        name = d["diet_name"][:38]
        score = d["confidence_score"]
        status_icon = "✅" if d["status"] == "approved" else "⏳"
        kb.button(
            text=f"{status_icon} {name} ({score:.0%})",
            callback_data=f"diet:{d['id']}"
        )
    kb.adjust(1)

    await message.answer(
        f"📊 Найдено {len(diets)} диет:\n"
        f"(выбери для подробностей)",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


# ── /pending ────────────────────────────────────────

@router.message(Command("pending"))
@router.message(F.text == "⏳ Ожидают оценки")
async def cmd_pending(message: Message):
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        diets = await search_diets(db, status="pending_verification", limit=10)

    if not diets:
        await message.answer("✅ Очередь модерации пуста")
        return

    kb = InlineKeyboardBuilder()
    for d in diets:
        name = d["diet_name"][:35]
        score = d["confidence_score"]
        kb.button(
            text=f"⏳ {name} ({score:.0%})",
            callback_data=f"pending_diet:{d['id']}"
        )
    kb.adjust(1)

    await message.answer(
        f"⏳ <b>На модерации: {len(diets)}</b>\n"
        f"Выбери диету для оценки:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


# ── /dlq ─────────────────────────────────────────────

@router.message(Command("dlq"))
@router.message(F.text == "🚨 Ошибки (DLQ)")
async def cmd_dlq(message: Message):
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM dlq ORDER BY failed_at DESC LIMIT 10"
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await message.answer("✅ DLQ пуста — ошибок нет")
        return

    text = f"🚨 <b>Dead Letter Queue ({len(rows)} записей)</b>\n\n"
    for r in rows[:5]:
        err = (r["error_reason"] or "")[:80]
        text += (
            f"• <code>{r['task_id'][:16]}</code>\n"
            f"  Ошибка: {err}\n"
            f"  Время: {r['failed_at']}\n\n"
        )

    await message.answer(text[:4000], parse_mode="HTML", reply_markup=_main_kb())


# ── Деталь диеты (callback) ────────────────────────────

async def _send_diet_detail(callback: CallbackQuery, diet_id: str, with_moderation: bool = False):
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        diet = await get_diet_by_id(db, diet_id)

    if not diet:
        await callback.answer("❌ Не найдено", show_alert=True)
        return

    allowed = diet.get("allowed_foods", [])[:10]
    forbidden = diet.get("forbidden_foods", [])[:5]
    contraind = diet.get("contraindications", [])[:5]

    text = (
        f"🥗 <b>{diet['diet_name']}</b>\n"
        f"⭐ Уверенность: {diet['confidence_score']:.0%}\n"
        f"🟢 Статус: {diet['status']}\n\n"
    )
    if allowed:
        text += "✅ <b>Разрешено:</b>\n" + "\n".join(f"  • {f}" for f in allowed) + "\n\n"
    if forbidden:
        text += "❌ <b>Запрещено:</b>\n" + "\n".join(f"  • {f}" for f in forbidden) + "\n\n"
    if contraind:
        text += "⚠️ <b>Противопоказания:</b>\n" + "\n".join(f"  • {c}" for c in contraind)
    if diet.get("source_url"):
        text += f"\n\n🔗 <a href='{diet['source_url']}'>Источник</a>"

    markup = None
    if with_moderation and diet["status"] == "pending_verification":
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Одобрить",  callback_data=f"verify:approve:{diet_id}")
        kb.button(text="❌ Отклонить", callback_data=f"verify:reject:{diet_id}")
        kb.adjust(2)
        markup = kb.as_markup()

    await callback.message.answer(text[:4000], parse_mode="HTML", reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("diet:"))
async def diet_detail(callback: CallbackQuery):
    diet_id = callback.data.split(":", 1)[1]
    await _send_diet_detail(callback, diet_id, with_moderation=False)


@router.callback_query(F.data.startswith("pending_diet:"))
async def pending_diet_detail(callback: CallbackQuery):
    diet_id = callback.data.split(":", 1)[1]
    await _send_diet_detail(callback, diet_id, with_moderation=True)


# ── verify callback ──────────────────────────────────────

@router.callback_query(F.data.startswith("verify:"))
async def verify_callback(callback: CallbackQuery):
    _, action, diet_id = callback.data.split(":", 2)
    approved = action == "approve"
    trace_id = new_trace_id()

    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        ok = await verify_diet(db, diet_id, approved, "moderator", trace_id)

    if ok:
        icon = "✅" if approved else "❌"
        label = "Одобрено" if approved else "Отклонено"
        await callback.answer(f"{icon} {label}", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
    else:
        await callback.answer("❌ Ошибка обновления", show_alert=True)


# ── запуск ───────────────────────────────────────────

async def start_bot():
    from bot_handlers.recipes import router as recipes_router
    from bot_handlers.schedule import router as schedule_router
    from bot_handlers.diet_picker import router as picker_router
    from bot_handlers.reactions import router as reactions_router
    from bot_handlers.meal_schedule_v2 import router as meal_v2_router
    from bot_handlers.cabinet import router as cabinet_router
    from bot_handlers.puhlyash_settings import router as puhlyash_router
    from aiogram.fsm.storage.memory import MemoryStorage
    bot = Bot(token=cfg.telegram_bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(reactions_router)  # callbacks: лайки, мастер
    dp.include_router(puhlyash_router)   # настройка Пухляша + тест
    dp.include_router(meal_v2_router)    # расписание v2
    dp.include_router(cabinet_router)    # FSM кабинета
    dp.include_router(picker_router)     # FSM подбора диеты
    dp.include_router(recipes_router)    # FSM рецептов
    dp.include_router(schedule_router)   # старый schedule (fallback)
    dp.include_router(router)            # общие хендлеры
    log.info("🥬 Telegram bot (Пухляш) starting...")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"], polling_timeout=20)
