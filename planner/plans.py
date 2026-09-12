"""planner.plans — weekly_plans (ADR-2): недельные планы с календарными границами.

Инварианты:
- PATCH-1: неделя владеет ``start_date``/``end_date`` (ISO 'YYYY-MM-DD' в tz
  пользователя), ``end_date = start_date + 6 дней``; неделя НЕ восстанавливается
  косвенно через meal_state;
- PATCH-3 (обязателен): одна ``active`` неделя на программу — физическая линия
  partial unique index ``idx_one_active_plan_per_program`` + кодовая проверка;
- ``days`` хранятся как JSON в текущем формате генератора (ADR-2 — не нормализуем).
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import aiosqlite

from planner.tz import (
    WeekBoundsError,
    date_to_str,
    str_to_date,
    today_local,
    utc_ts_string,
    validate_week_dates,
)

__all__ = [
    "PlanError",
    "create_plan",
    "create_plan_from_days",
    "get_active_plan",
    "get_active_plan_for_user",
    "archive_plan",
    "list_plans",
]

PLAN_STATUSES = ("active", "archived")


class PlanError(ValueError):
    """Некорректный аргумент или нарушение инварианта плана."""


async def _ensure_plan_table(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_plans (
            id          TEXT PRIMARY KEY,
            program_id  TEXT NOT NULL,
            tg_id       TEXT NOT NULL,
            week_no     INTEGER NOT NULL DEFAULT 1,
            start_date  TEXT NOT NULL,
            end_date    TEXT NOT NULL,
            days        TEXT NOT NULL DEFAULT '[]',
            shopping_list TEXT NOT NULL DEFAULT '[]',
            tips        TEXT NOT NULL DEFAULT '[]',
            status      TEXT NOT NULL DEFAULT 'active',
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_plan_per_program "
        "ON weekly_plans(program_id) WHERE status = 'active'"
    )


def _validate_days(days: list) -> None:
    if not isinstance(days, list) or not days:
        raise PlanError("days must be a non-empty list")
    if len(days) > 7:
        raise PlanError(f"days has {len(days)} entries, expected <= 7")


async def create_plan(
    db: aiosqlite.Connection,
    program_id: str,
    tg_id: str,
    *,
    week_no: int = 1,
    start_date: Any = None,
    end_date: Any = None,
    days: list | None = None,
    shopping_list: list | None = None,
    tips: list | None = None,
    user_timezone: str | None = None,
) -> dict:
    """Создать недельный план.

    Календарная семантика (PATCH-1/ADR-6): даты вычисляются в tz пользователя
    (``user_timezone``); если ``start_date`` не передана — берётся «сегодня»
    в tz пользователя; ``end_date`` обязана быть ``start_date + 6 дней``
    (проверка кодом + физический индекс остаётся последней линией).
    """
    if not program_id or not tg_id:
        raise PlanError("program_id and tg_id are required")

    if start_date is None:
        start = today_local(user_timezone)
    elif isinstance(start_date, str):
        start = str_to_date(start_date)
    else:
        start = start_date

    if end_date is None:
        from planner.tz import week_bounds
        end = week_bounds(start)[1]
    elif isinstance(end_date, str):
        end = str_to_date(end_date)
    else:
        end = end_date

    try:
        validate_week_dates(start, end)  # PATCH-1: end == start + 6
    except WeekBoundsError as exc:
        raise PlanError(str(exc)) from exc  # единый тип ошибки plans-API
    days = days if days is not None else []
    if days:
        _validate_days(days)  # непустой days обязан быть валидным списком дней (<=7)
    # пустой days разрешён: схема-план без контента (C-3 всегда передаёт реальные дни)

    plan_id = str(uuid.uuid4())
    ts = utc_ts_string()
    try:
        await db.execute("BEGIN")
        await _ensure_plan_table(db)
        cur = await db.execute(
            "SELECT id FROM weekly_plans WHERE program_id=? AND status='active'",
            (program_id,),
        )
        old = await cur.fetchone()
        if old is not None:
            # новая неделя архивирует предыдущую active той же программы
            await db.execute(
                "UPDATE weekly_plans SET status='archived' WHERE id=?", (old["id"],)
            )
        await db.execute(
            "INSERT INTO weekly_plans (id, program_id, tg_id, week_no, start_date, "
            "end_date, days, shopping_list, tips, status, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (plan_id, program_id, str(tg_id), int(week_no), date_to_str(start),
             date_to_str(end), json.dumps(days, ensure_ascii=False),
             json.dumps(shopping_list or [], ensure_ascii=False),
             json.dumps(tips or [], ensure_ascii=False), "active", ts),
        )
        await db.commit()
    except aiosqlite.IntegrityError as exc:
        await db.rollback()
        raise PlanError(
            "active plan already exists for this program (DB invariant)"
        ) from exc
    except Exception:
        await db.rollback()
        raise

    cur = await db.execute(
        "SELECT * FROM weekly_plans WHERE id=? AND tg_id=?",
        (plan_id, str(tg_id)),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def create_plan_from_days(
    db: aiosqlite.Connection,
    program_id: str,
    tg_id: str,
    days: list,
    *,
    shopping_list: list | None = None,
    tips: list | None = None,
    week_no: int = 1,
    user_timezone: str | None = None,
) -> dict:
    """Тонкая обёртка над create_plan для формата LLM-генератора (days обязателен)."""
    if not days:
        raise PlanError("days is required for create_plan_from_days")
    return await create_plan(
        db, program_id, tg_id,
        week_no=week_no, days=days, shopping_list=shopping_list, tips=tips,
        user_timezone=user_timezone,
    )


async def get_active_plan(db: aiosqlite.Connection, program_id: str, tg_id: str) -> dict | None:
    """Активная неделя программы — второе звено canonical chain (PATCH-2)."""
    cur = await db.execute(
        "SELECT * FROM weekly_plans WHERE program_id=? AND tg_id=? AND status='active'",
        (program_id, str(tg_id)),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_active_plan_for_user(db: aiosqlite.Connection, tg_id: str) -> dict | None:
    """Удобство: active plan по active program пользователя (полная цепочка)."""
    from planner.programs import get_active_program
    program = await get_active_program(db, tg_id)
    if program is None:
        return None
    return await get_active_plan(db, program["id"], tg_id)


async def archive_plan(db: aiosqlite.Connection, plan_id: str, tg_id: str) -> bool:
    """active → archived (восстановление не предусмотрено — создаётся новая неделя)."""
    try:
        await db.execute("BEGIN")
        cur = await db.execute(
            "UPDATE weekly_plans SET status='archived' WHERE id=? AND tg_id=? AND status='active'",
            (plan_id, str(tg_id)),
        )
        ok = cur.rowcount == 1
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return ok


async def list_plans(db: aiosqlite.Connection, program_id: str, tg_id: str) -> list[dict]:
    """История недель программы (новые сверху) — данные для адаптации Phase 2."""
    cur = await db.execute(
        "SELECT * FROM weekly_plans WHERE program_id=? AND tg_id=? "
        "ORDER BY week_no DESC, created_at DESC",
        (program_id, str(tg_id)),
    )
    return [dict(r) for r in await cur.fetchall()]
