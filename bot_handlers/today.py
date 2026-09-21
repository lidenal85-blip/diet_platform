"""bot_handlers.today — экран «Сегодня» (C-3.2, 2026-09-19; C-3.2.1, 2026-09-21).

C-3.2.1 — визуальная группировка по блюдам: у каждого приёма свой блок
клавиатуры — секционная кнопка-заголовок (приём · блюдо · статус) и
непосредственно под ней его 2 ряда действий. Логика действий, переходы,
идемпотентность, события и принадлежность записи не менялись.

Reader-first (аудит C3_AUDIT_2026-09-19.md, владелец одобрил C-3.2):
- данные ТОЛЬКО через canonical chain planner.get_today_meals()
  (user → active diet_program → active weekly_plan → meal_state на день);
- отметки через planner.set_meal_status() (транзакция, writer planner);
- событие meal_status_changed через planner.log_event() — только при факте
  изменения; сбой события не ломает пользовательский флоу (own-try, как в
  diet_picker);
- «Заменить» и «Рецепт» — заглушки: без LLM, без записи в meal_state,
  без генерации рецептов (их этапы — позже, вне C-3.2).

Границы C-3.2: БД-схема не меняется; «Мой план» — C-3.3; замены и
рецепты из плана — следующие этапы; никакой повторной генерации плана.
"""
from __future__ import annotations

import json
from typing import Optional

import aiosqlite
from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot_handlers.keyboards import main_kb
from building_blocks.logger import get_logger
from database import DB_PATH
import planner
from planner.tz import today_local

log = get_logger(__name__)
router = Router(name="today")

# ── Callback-контракт (§2 промпта C-3.2) ────────────────────────────────────
# ms:{meal_state_id}:{eat|skip|replace|recipe}; только UUID записи — никаких
# персональных данных или текстов блюд в callback_data (64 байта Telegram).
_PREFIX = "ms:"
_ACTIONS = ("eat", "skip", "replace", "recipe")

_SLOT_TITLES = {
    "breakfast": "🌅 Завтрак",
    "lunch": "🍽 Обед",
    "dinner": "🌙 Ужин",
    "snack": "🍎 Перекус",
}

_STATUS_BADGE = {
    "planned": "",
    "eaten": " ✅",
    "skipped": " ⏭",
    "replaced": " 🔁",
    "missed": " 💤",
}

# Человекочитаемый статус для инфо-алерта кнопки-заголовка (C-3.2.1).
_STATUS_LABEL = {
    "planned": "запланировано",
    "eaten": "съедено ✅",
    "skipped": "пропущено ⏭",
    "replaced": "заменено 🔁",
    "missed": "пропущено 💤",
}

# Префикс callback секционных заголовков-блоков (C-3.2.1):
# today:meal:{meal_state_id} — только UUID, без персональных данных.
_MEAL_HEADER_PREFIX = "today:meal:"


def meal_kb(meal_id: str) -> InlineKeyboardMarkup:
    """Клавиатура действий одного приёма пищи (§1-5 промпта)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Съел", callback_data=f"ms:{meal_id}:eat"),
                InlineKeyboardButton(text="⏭ Пропустил", callback_data=f"ms:{meal_id}:skip"),
            ],
            [
                InlineKeyboardButton(text="🔁 Заменить", callback_data=f"ms:{meal_id}:replace"),
                InlineKeyboardButton(text="📖 Рецепт", callback_data=f"ms:{meal_id}:recipe"),
            ],
        ]
    )


def _parse_ms_callback(data: Optional[str]) -> Optional[tuple[str, str]]:
    """ms:{id}:{action} → (id, action) | None (безопасно для любого мусора)."""
    if not data or not data.startswith(_PREFIX):
        return None
    parts = data[len(_PREFIX):].split(":", 1)
    if len(parts) != 2:
        return None
    meal_id, action = parts
    if not meal_id or action not in _ACTIONS:
        return None
    return meal_id, action


def _fmt_meal(m: dict) -> str:
    """Строка одного приёма: только реально возвращаемые planner поля."""
    title = _SLOT_TITLES.get(m["meal_slot"], m["meal_slot"])
    badge = _STATUS_BADGE.get(m["status"], "")
    name = (m.get("planned_text") or "").strip()
    line = f"{title}{badge}"
    if name:
        line += f" — {name}"
    return line


def _meal_header_text(m: dict) -> str:
    """Текст кнопки-заголовка блока блюда (C-3.2.1): приём · блюдо · статус.

    Название блюда обрезается до 30 символов — кнопка остаётся компактной
    на мобильном экране.
    """
    title = _SLOT_TITLES.get(m["meal_slot"], m["meal_slot"])
    badge = _STATUS_BADGE.get(m["status"], "")
    name = (m.get("planned_text") or "").strip()
    if not name:
        return f"{title}{badge}"
    short = name if len(name) <= 30 else name[:29].rstrip() + "…"
    return f"{title}{badge} · {short}"


def _render_screen(meals: list[dict]) -> str:
    """Текст экрана «Сегодня» из фактических данных meal_state."""
    lines = ["📅 <b>Что у нас на сегодня</b>", ""]
    lines.extend(_fmt_meal(m) for m in meals)
    eaten = sum(1 for m in meals if m["status"] == "eaten")
    skipped = sum(1 for m in meals if m["status"] == "skipped")
    left = len(meals) - eaten - skipped
    tail = f"\n✅ Съедено: {eaten} из {len(meals)}"
    if skipped:
        tail += f" · ⏭ пропущено: {skipped}"
    if left:
        tail += f" · осталось: {left}"
    return "\n".join(lines) + tail


async def _fetch_meal(db: aiosqlite.Connection, meal_id: str) -> Optional[dict]:
    """Одна запись meal_state по id (принадлежность проверяет вызывающий)."""
    cur = await db.execute("SELECT * FROM meal_state WHERE id=?", (meal_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


def _empty_screen() -> str:
    """Пустое состояние: нет активной программы/плана/блюд (без генерации)."""
    return (
        "📅 <b>Сегодня</b>\n\n"
        "Активного плана пока нет 🤷‍♂️\n\n"
        "Жми «🎯 Подобрать диету» — составлю план на неделю, "
        "и «Сегодня» оживёт."
    )


def _today_kb_with_refresh(meals: list[dict]) -> InlineKeyboardMarkup:
    """Клавиатура экрана блоками по блюдам (C-3.2.1).

    На каждый приём: ряд-заголовок (приём · блюдо · статус, нажатие —
    инфо-алерт) и сразу под ним его 2 ряда действий. В конце — «Обновить».
    Секционные заголовки — канонический Telegram-паттерн привязки кнопок
    к пункту списка (inline-кнопки нельзя вставить между строками текста).
    """
    rows: list[list[InlineKeyboardButton]] = []
    for m in meals:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_meal_header_text(m),
                    callback_data=f"{_MEAL_HEADER_PREFIX}{m['id']}",
                )
            ]
        )
        rows.extend(meal_kb(m["id"]).inline_keyboard)
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="today:refresh")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text.in_({"📅 Сегодня", "/today"}))
async def cmd_today(message: Message) -> None:
    """Вход в экран: кнопка «📅 Сегодня» или команда /today."""
    tg_id = str(message.from_user.id)
    await send_today_screen(message, tg_id)


async def send_today_screen(message: Message, tg_id: str) -> None:
    """Отправить экран «Сегодня» (public API; используется и переходом из
    «Мой план» — C-3.3). Поведение cmd_today сохранено 1:1."""
    try:
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            db.row_factory = aiosqlite.Row
            meals = await planner.get_today_meals(db, tg_id)
    except Exception as e:
        log.error("cmd_today db error: %s", e)
        await message.answer("😔 Что-то пошло не так. Попробуй ещё раз через минуту.")
        return

    if not meals:
        await message.answer(_empty_screen(), parse_mode="HTML", reply_markup=main_kb())
        return

    # Первый real-ридер canonical chain: фиксируем просмотр (§14)
    try:
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            await planner.log_event(db, "plan_viewed", tg_id, {"screen": "today"})
            await db.commit()
    except Exception as e:
        log.warning("plan_viewed not logged: %s", e)

    await message.answer(
        _render_screen(meals),
        parse_mode="HTML",
        reply_markup=_today_kb_with_refresh(meals),
    )


@router.callback_query(F.data.startswith(_MEAL_HEADER_PREFIX))
async def today_meal_info(call: CallbackQuery) -> None:
    """Нажатие заголовка блока блюда: инфо-алерт о блюде и его статусе.

    Только чтение meal_state; принадлежность проверяется так же, как в
    _handle_status (чужая/устаревшая — без изменений и без падений).
    """
    meal_id = call.data[len(_MEAL_HEADER_PREFIX):]
    if not meal_id or len(meal_id) > 64:
        await call.answer("⚠️ Неактуальная кнопка", show_alert=True)
        return
    tg_id = str(call.from_user.id)
    try:
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            db.row_factory = aiosqlite.Row
            meal = await _fetch_meal(db, meal_id)
    except Exception as e:
        log.error("today_meal_info db error: %s", e)
        await call.answer("😔 Не получилось, попробуй ещё раз", show_alert=True)
        return
    if meal is None or meal["tg_id"] != tg_id:
        await call.answer("⚠️ Запись не найдена", show_alert=True)
        return
    title = _SLOT_TITLES.get(meal["meal_slot"], meal["meal_slot"])
    name = (meal.get("planned_text") or "").strip()
    status = _STATUS_LABEL.get(meal["status"], meal["status"])
    alert = f"{title}\n{name}\n\nСтатус: {status}" if name else f"{title}\n\nСтатус: {status}"
    await call.answer(alert[:200], show_alert=True)  # лимит Telegram 200 симв.


@router.callback_query(F.data == "today:refresh")
async def today_refresh(call: CallbackQuery) -> None:
    """«🔄 Обновить»: перечитать meal_state и перерисовать текст+клавиатуру."""
    tg_id = str(call.from_user.id)
    try:
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            db.row_factory = aiosqlite.Row
            meals = await planner.get_today_meals(db, tg_id)
    except Exception as e:
        log.error("today_refresh db error: %s", e)
        await call.answer("😔 Не получилось, попробуй ещё раз", show_alert=True)
        return
    if not meals:
        await call.answer("📅 План закончился", show_alert=True)
        return
    try:
        await call.message.edit_text(
            _render_screen(meals), parse_mode="HTML",
            reply_markup=_today_kb_with_refresh(meals),
        )
    except Exception:
        pass  # Telegram «message is not modified» — текст и так актуален
    await call.answer()


# ── eaten / skipped (§3 промпта) ────────────────────────────────────────────

async def _handle_status(call: CallbackQuery, new_status: str) -> None:
    """Общая логика eaten/skip: принадлежность → no-op-проверка → запись.

    Никаких событий и ответов «сделано», если запись не изменилась.
    """
    parsed = _parse_ms_callback(call.data)
    if parsed is None:
        await call.answer("⚠️ Неактуальная кнопка", show_alert=True)
        return
    meal_id, _action = parsed
    tg_id = str(call.from_user.id)

    try:
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            db.row_factory = aiosqlite.Row
            meal = await _fetch_meal(db, meal_id)
            if meal is None or meal["tg_id"] != tg_id:
                # чужая/устаревшая запись — не падаем, не меняем
                await call.answer("⚠️ Запись не найдена", show_alert=True)
                return
            if meal["status"] == new_status:
                await call.answer("Уже отмечено ✅")
                return
            if meal["status"] != "planned":
                # planned → eaten|skipped — единственные переходы C-3.2;
                # повторная смена (eaten→skip и т.п.) не в рамках этапа
                await call.answer("Статус уже изменён — обнови экран 🔄", show_alert=True)
                return

            day = meal["day_date"]  # экран всегда открывает день = сегодня
            updated = await planner.set_meal_status(
                db, meal["plan_id"], tg_id, day, meal["meal_slot"], new_status
            )
            if updated is None:
                await call.answer("⚠️ Запись не найдена", show_alert=True)
                return
            # Событие только при факте изменения (§3.4). Props минимальны:
            # служебные идентификаторы, без текстов блюд и данных профиля.
            try:
                await planner.log_event(
                    db, "meal_status_changed", tg_id,
                    {
                        "meal_state_id": meal_id,
                        "plan_id": meal["plan_id"],
                        "day_date": day,
                        "meal_slot": meal["meal_slot"],
                        "from_status": meal["status"],
                        "to_status": new_status,
                    },
                )
                await db.commit()
            except Exception as e:
                # own-try: сбой аналитики не отменяет отметку (как в diet_picker)
                log.warning("meal_status_changed not logged: %s", e)
    except Exception as e:
        log.error("_handle_status db error: %s", e)
        await call.answer("😔 Не получилось, попробуй ещё раз", show_alert=True)
        return

    await call.answer("✅ Съел" if new_status == "eaten" else "⏭ Пропустил")
    # 5) пользователь видит актуальный статус: перерисовываем экран
    await _redraw(call, tg_id)


async def _redraw(call: CallbackQuery, tg_id: str) -> None:
    """Перерисовать экран «Сегодня» после изменения статуса."""
    try:
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            db.row_factory = aiosqlite.Row
            meals = await planner.get_today_meals(db, tg_id)
    except Exception as e:
        log.error("_redraw db error: %s", e)
        return
    if not meals:
        return
    try:
        await call.message.edit_text(
            _render_screen(meals), parse_mode="HTML",
            reply_markup=_today_kb_with_refresh(meals),
        )
    except Exception:
        pass  # «message is not modified» и т.п. — не критично


@router.callback_query(F.data.startswith("ms:") & F.data.endswith(":eat"))
async def ms_eat(call: CallbackQuery) -> None:
    await _handle_status(call, "eaten")


@router.callback_query(F.data.startswith("ms:") & F.data.endswith(":skip"))
async def ms_skip(call: CallbackQuery) -> None:
    await _handle_status(call, "skipped")


# ── replace / recipe — заглушки C-3.2 (§4 промпта) ──────────────────────────

@router.callback_query(F.data.startswith("ms:") & F.data.endswith(":replace"))
async def ms_replace(call: CallbackQuery) -> None:
    """Без записи в БД, без LLM: честное «позже» (замены — отдельный этап)."""
    await call.answer(
        "🔁 Замена блюд появится позже — сейчас просто отметь «✅ Съел» или «⏭ Пропустил»",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("ms:") & F.data.endswith(":recipe"))
async def ms_recipe(call: CallbackQuery) -> None:
    """Без генерации и без новых LLM-вызовов (§4). Если к слоту уже привязан
    сохранённый рецепт — показываем его; иначе честное «пока не подключён».
    """
    parsed = _parse_ms_callback(call.data)
    if parsed is None:
        await call.answer("⚠️ Неактуальная кнопка", show_alert=True)
        return
    meal_id, _ = parsed
    tg_id = str(call.from_user.id)
    try:
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            db.row_factory = aiosqlite.Row
            meal = await _fetch_meal(db, meal_id)
            if meal is None or meal["tg_id"] != tg_id:
                await call.answer("⚠️ Запись не найдена", show_alert=True)
                return
            recipe_id = meal.get("recipe_id")
            if not recipe_id:
                await call.answer(
                    "📖 Просмотр рецепта пока не подключён — придёт отдельным обновлением",
                    show_alert=True,
                )
                return
            async with db.execute(
                "SELECT title, description, ingredients, steps FROM recipes WHERE id=?",
                (recipe_id,),
            ) as cur:
                row = await cur.fetchone()
    except Exception as e:
        log.error("ms_recipe db error: %s", e)
        await call.answer("😔 Не получилось, попробуй ещё раз", show_alert=True)
        return
    if row is None:
        await call.answer("⚠️ Рецепт не найден", show_alert=True)
        return
    title = (row["title"] or "Рецепт").strip()

    def _as_list(raw: object) -> list[str]:
        try:
            val = json.loads(raw) if isinstance(raw, str) else (raw or [])
            return [str(x) for x in val] if isinstance(val, list) else []
        except Exception:
            return []

    ingredients = _as_list(row["ingredients"])
    steps = _as_list(row["steps"])
    lines = [f"📖 <b>{title}</b>"]
    if (row["description"] or "").strip():
        lines.append("")
        lines.append(row["description"].strip())
    if ingredients:
        lines += ["", "🧺 <b>Ингредиенты:</b>"] + [f"• {x}" for x in ingredients]
    if steps:
        lines += ["", "👩‍🍳 <b>Приготовление:</b>"]
        lines += [f"{i}. {s}" for i, s in enumerate(steps, 1)]
    text = "\n".join(lines)
    # только показ сохранённого — никаких генераций
    await call.message.answer(text[:4000], parse_mode="HTML")
    await call.answer()


# Разбор planned_ref (JSON) может понадобиться следующим этапам; здесь данные
# блюда берутся только из денормализованного planned_text (без выдумок).
def _planned_ref(m: dict) -> dict:
    try:
        ref = json.loads(m.get("planned_ref") or "{}")
        return ref if isinstance(ref, dict) else {}
    except Exception:
        return {}
