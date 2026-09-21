"""bot_handlers.my_plan — экран «Мой план» (C-3.3, 2026-09-21).

Reader-экран недельного плана, дополняющий «Сегодня» (C-3.2/C-3.2.1):
- данные ТОЛЬКО через canonical chain: planner.get_week_overview()
  (user → active diet_program → active weekly_plan → meal_state; archived/
  replaced не участвуют, календарные даты — из weekly_plans.start_date);
- никаких записей в БД, никаких LLM-вызовов, никакой генерации — только
  чтение сохранённого плана;
- «Заменить»/«Рецепт» остаются на экране «Сегодня» (C-3.2) — здесь действий
  с приёмами нет: обзор недели, инфо-алерт дня и переход к «Сегодня»;
- просмотр фиксируется событием plan_viewed (как в today.cmd_today),
  без чувствительных данных.

Границы C-3.3: БД-схема не меняется; история недель и замены блюд — не в
этом этапе.
"""
from __future__ import annotations

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

log = get_logger(__name__)
router = Router(name="my_plan")

# ── Callback-контракт (минимальный, без персональных данных) ────────────────
# mp:{plan_id}:{day_index 1..7} — id активной недели + номер дня; владелец
# кнопки проверяется через canonical chain: данные читаются только из активной
# недели самого tg_id, чужой plan_id в callback просто не совпадёт.
_DAY_PREFIX = "mp:"
_REFRESH = "mp:refresh"
_TODAY_OPEN = "today:open"  # переход на экран «Сегодня»

_SLOT_TITLES = {
    "breakfast": "🌅 Завтрак",
    "lunch": "🍽 Обед",
    "dinner": "🌙 Ужин",
    "snack": "🍎 Перекус",
}

# Значки статусов — та же семантика, что на «Сегодня» (today._STATUS_BADGE)
_STATUS_BADGE = {
    "eaten": " ✅",
    "skipped": " ⏭",
    "replaced": " 🔁",
    "missed": " 💤",
}

_WEEKDAY_TITLES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _empty_screen() -> str:
    """Пустое состояние: нет активной программы/недели (без генерации)."""
    return (
        "🗺 <b>Мой план</b>\n\n"
        "Активной программы пока нет 🤷‍♂️\n\n"
        "Жми «🎯 Подобрать диету» — составлю программу и план на неделю."
    )


async def _load_overview(tg_id: str):
    """Canonical chain через planner.get_week_overview.

    Возвращает dict обзора, None (нет активных данных) или строку "error"
    (сбой БД — пользователь получает аккуратное «попробуй позже»).
    """
    try:
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            db.row_factory = aiosqlite.Row
            return await planner.get_week_overview(db, tg_id)
    except Exception as e:
        log.error("_load_overview db error: %s", e)
        return "error"


def _fmt_date(iso: str) -> str:
    """«21.09» из ISO-даты; при любой неожиданности — исходная строка."""
    try:
        _y, m, d = iso.split("-")
        return f"{d}.{m}"
    except Exception:
        return iso


def _render_screen(week: dict, diet_name: Optional[str] = None) -> str:
    """Текст обзора недели: 7 дней с датами, блюдами и статусами."""
    head = "🗺 <b>Мой план</b>"
    if diet_name:
        head += f"\n🍽 Программа: <b>{diet_name}</b>"
    lines = [head]
    for day in week["days"]:
        date_s = _fmt_date(day["date"])
        if day["meals"]:
            parts = []
            for m in day["meals"]:
                title = _SLOT_TITLES.get(m["meal_slot"], m["meal_slot"])
                badge = _STATUS_BADGE.get(m["status"], "")
                name = (m.get("planned_text") or "").strip()
                # формат строки приёма — зеркало «Сегодня» (today._fmt_meal):
                # «🌅 Завтрак ✅ — Овсянка»; обзор без блюд бесполезен
                parts.append(f"{title}{badge} — {name}" if name else f"{title}{badge}")
            meals_s = " · ".join(parts)
        else:
            meals_s = "—"
        marker = " 📍" if day["is_today"] else ""
        lines.append(f"\n<b>{day['day_title']} · {date_s}{marker}</b>\n{meals_s}")
    eaten = sum(1 for d in week["days"] for m in d["meals"] if m["status"] == "eaten")
    total = sum(len(d["meals"]) for d in week["days"])
    lines.append(f"\n✅ Съедено за неделю: {eaten} из {total}")
    lines.append("📍 — сегодня. Нажми день, чтобы увидеть блюда подробнее")
    return "\n".join(lines)


def _week_kb(plan_id: str, week: dict) -> InlineKeyboardMarkup:
    """Кнопки: дни с приёмами (инфо-алерт), «Сегодня», «Обновить»."""
    rows: list[list[InlineKeyboardButton]] = []
    for day in week["days"]:
        if not day["meals"]:
            continue  # день без записей meal_state не даёт действия
        label = f"📅 {day['day_title']} · {_fmt_date(day['date'])}"
        if day["is_today"]:
            label = f"📍 {label}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label[:64],
                    callback_data=f"{_DAY_PREFIX}{plan_id}:{day['day_index'] + 1}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="📅 Сегодня", callback_data=_TODAY_OPEN),
            InlineKeyboardButton(text="🔄 Обновить", callback_data=_REFRESH),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _log_plan_viewed(tg_id: str, screen: str) -> None:
    """plan_viewed — own-try, сбой аналитики не ломает экран."""
    try:
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            await planner.log_event(db, "plan_viewed", tg_id, {"screen": screen})
            await db.commit()
    except Exception as e:
        log.warning("plan_viewed not logged: %s", e)


async def _active_diet_name(tg_id: str) -> Optional[str]:
    """Название активной программы для заголовка (own-try, декоративно)."""
    try:
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            db.row_factory = aiosqlite.Row
            program = await planner.get_active_program(db, tg_id)
            return (program or {}).get("diet_name")
    except Exception as e:
        log.warning("_active_diet_name failed: %s", e)
        return None


async def send_my_plan(message: Message, tg_id: str) -> None:
    """Отправить экран «Мой план» (public API — используется и переходами)."""
    overview = await _load_overview(tg_id)
    if overview == "error":
        await message.answer("😔 Что-то пошло не так. Попробуй ещё раз через минуту.")
        return
    if overview is None:
        await message.answer(_empty_screen(), parse_mode="HTML", reply_markup=main_kb())
        return
    await _log_plan_viewed(tg_id, "my_plan")
    diet_name = await _active_diet_name(tg_id)
    await message.answer(
        _render_screen(overview, diet_name),
        parse_mode="HTML",
        reply_markup=_week_kb(overview["plan_id"], overview),
    )


@router.message(F.text.in_({"🗓 Мой план", "/myplan"}))
async def cmd_my_plan(message: Message) -> None:
    """Вход в экран: кнопка «🗓 Мой план» или команда /myplan."""
    if message.from_user is None:
        return
    await send_my_plan(message, str(message.from_user.id))


@router.callback_query(F.data == _TODAY_OPEN)
async def go_today(call: CallbackQuery) -> None:
    """«📅 Сегодня»: переход на экран дня (публичный хелпер «Сегодня»)."""
    from bot_handlers.today import send_today_screen

    try:
        await send_today_screen(call.message, str(call.from_user.id))
    except Exception as e:
        log.error("go_today failed: %s", e)
        await call.answer("😔 Не получилось, попробуй ещё раз", show_alert=True)
        return
    await call.answer()


@router.callback_query(F.data == _REFRESH)
async def my_plan_refresh(call: CallbackQuery) -> None:
    """«🔄 Обновить»: перечитать неделю и перерисовать экран."""
    tg_id = str(call.from_user.id)
    overview = await _load_overview(tg_id)
    if overview == "error":
        await call.answer("😔 Не получилось, попробуй ещё раз", show_alert=True)
        return
    if overview is None:
        try:
            await call.message.edit_text(_empty_screen(), parse_mode="HTML")
        except Exception:
            pass
        await call.answer()
        return
    diet_name = await _active_diet_name(tg_id)
    try:
        await call.message.edit_text(
            _render_screen(overview, diet_name),
            parse_mode="HTML",
            reply_markup=_week_kb(overview["plan_id"], overview),
        )
    except Exception:
        pass  # «message is not modified» — текст и так актуален
    await call.answer()


@router.callback_query(F.data.startswith(_DAY_PREFIX))
async def day_info(call: CallbackQuery) -> None:
    """Кнопка дня: инфо-алерт с блюдами и статусами (только чтение).

    Ownership через canonical chain: читается только активная неделя самого
    tg_id; plan_id из callback служит scope-проверкой (чужой/устаревший id
    активной недели не совпадёт — отказ без изменений).
    """
    rest = call.data[len(_DAY_PREFIX):]
    try:
        plan_id, n_s = rest.rsplit(":", 1)
        n = int(n_s)
    except Exception:
        await call.answer("⚠️ Неактуальная кнопка", show_alert=True)
        return
    if not plan_id or not 1 <= n <= 7:
        await call.answer("⚠️ Неактуальная кнопка", show_alert=True)
        return
    tg_id = str(call.from_user.id)
    overview = await _load_overview(tg_id)
    if overview == "error":
        await call.answer("😔 Не получилось, попробуй ещё раз", show_alert=True)
        return
    if overview is None:
        await call.answer("⚠️ Активный план не найден", show_alert=True)
        return
    if overview["plan_id"] != plan_id:
        # чужая/устаревшая неделя — данные не выдаём, ничего не меняем
        await call.answer("⚠️ Неактуальная кнопка", show_alert=True)
        return
    day = next((d for d in overview["days"] if d["day_index"] == n - 1), None)
    if day is None or not day["meals"]:
        await call.answer("⚠️ День не найден", show_alert=True)
        return
    parts = [
        (
            f"{_SLOT_TITLES.get(m['meal_slot'], m['meal_slot'])} — "
            f"{(m['planned_text'] or '—').strip()} · "
            f"{'отмечено' if m['status'] != 'planned' else 'запланировано'}"
        )
        for m in day["meals"]
    ]
    label = f"📅 {day['day_title']} · {_fmt_date(day['date'])}"
    await call.answer(f"{label}\n\n" + "\n".join(parts)[:190], show_alert=True)
