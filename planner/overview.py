"""planner.overview — недельный обзор плана (C-3.3, 2026-09-21).

Reader-модуль домена Nutrition: ТОЛЬКО чтение по canonical chain (PATCH-2),
зеркало ``slots.get_today_meals`` на всю неделю:

    user → active diet_program → active weekly_plan → meal_state(дни недели)

Никаких записей, никаких synthetic rows, никаких новых сущностей — одна
SELECT-группа по существующей таблице meal_state. Возвращает только реально
существующие записи (как и «Сегодня»: слоты, не заведённые в плане, не
придумываются). Календарные даты дней — из weekly_plans.start_date + day_index
(PATCH-1: неделя владеет датами; meal_state.day_date — денормализация той же
календарной семантики).
"""
from __future__ import annotations

import json
from typing import Any

import aiosqlite

from planner.programs import get_active_program
from planner.slots import KNOWN_MEAL_SLOTS
from planner.tz import day_date_for, str_to_date, today_local

__all__ = ["get_week_overview"]


async def get_week_overview(
    db: aiosqlite.Connection,
    tg_id: str,
    *,
    today: Any = None,
    user_timezone: str | None = None,
) -> dict | None:
    """Активная неделя пользователя: 7 дней плана со статусами приёмов.

    Canonical chain (PATCH-2), как ``slots.get_today_meals``: сначала активная
    программа, затем активная неделя этой программы — archived/replaced не
    участвуют. Возвращает:

    - ``None`` — нет активной программы ИЛИ активной недели (экран покажет
      пустое состояние; генерация не запускается);
    - иначе dict ``{"plan_id", "start_date" (ISO), "days": [7 dict]}``, где
      каждый день: ``{"day_index", "date" (ISO str), "is_today", "day_title",
      "meals": [{"meal_slot", "status", "meal_state_id", "planned_text"}]}``.

    ``meals`` отсортированы по каноническому порядку слотов; отсутствующие в
    meal_state слоты плана не синтезируются. ``today``/``user_timezone`` —
    те же параметры, что у ``get_today_meals`` (совместимая семантика: дата
    «сегодня» в tz пользователя; отладочная подмена ``today`` для тестов).
    """
    if today is None:
        today = today_local(user_timezone)
    if hasattr(today, "isoformat"):
        today_str = today.isoformat()
    else:
        today_str = str_to_date(str(today)).isoformat()

    program = await get_active_program(db, tg_id)
    if program is None:
        return None
    cur = await db.execute(
        "SELECT * FROM weekly_plans WHERE program_id=? AND tg_id=? AND status='active'",
        (program["id"], str(tg_id)),
    )
    plan_row = await cur.fetchone()
    if plan_row is None:
        return None
    plan = dict(plan_row)

    try:
        days_json = json.loads(plan.get("days") or "[]")
    except Exception:
        days_json = []
    if not isinstance(days_json, list):
        days_json = []

    cur = await db.execute(
        "SELECT id, day_date, meal_slot, status, planned_text "
        "FROM meal_state WHERE plan_id=?",
        (plan["id"],),
    )
    by_date: dict[str, list[dict]] = {}
    for r in await cur.fetchall():
        m = dict(r)
        by_date.setdefault(m["day_date"], []).append(m)

    order = {slot: i for i, slot in enumerate(KNOWN_MEAL_SLOTS)}
    plan_start = str_to_date(plan["start_date"])
    week: list[dict] = []
    for day_index in range(7):
        day = days_json[day_index] if day_index < len(days_json) else {}
        if not isinstance(day, dict):
            day = {}
        date = day_date_for(plan_start, day_index)
        date_str = date.isoformat()
        meals = sorted(
            by_date.get(date_str, []),
            key=lambda m: order.get(m["meal_slot"], len(order)),
        )
        week.append(
            {
                "day_index": day_index,
                "date": date_str,
                "is_today": date_str == today_str,
                "day_title": str(day.get("day") or f"День {day_index + 1}"),
                "meals": [
                    {
                        "meal_slot": m["meal_slot"],
                        "status": m["status"],
                        "meal_state_id": m["id"],
                        "planned_text": m.get("planned_text") or "",
                    }
                    for m in meals
                ],
            }
        )
    return {"plan_id": plan["id"], "start_date": plan["start_date"], "days": week}
