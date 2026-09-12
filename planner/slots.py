"""planner.slots — meal_state (ADR-3) + canonical chain (PATCH-2) + bundle (PATCH-5).

Ключевые правила:
- **PATCH-2:** «что есть сегодня» = ``user → active diet_program → active
  weekly_plan → meal_state(plan_id, day_date=today)``. Прямой запрос
  ``WHERE tg_id=? AND day_date=?`` источником истины НЕ является.
- **PATCH-4:** meal_state = materialized state ТОЛЬКО для фактически
  запланированных meal slots; никакого шаблона 7×4=28, никаких synthetic rows.
- **PATCH-5:** LLM-вызов идёт ДО транзакции; ``persist_plan_bundle`` принимает
  уже валидированные данные и пишет всё атомарно в одной короткой транзакции
  (LLM → validate → BEGIN → writes → COMMIT).
- **PATCH-10:** ``day_date`` — локальная дата пользователя (tz-хелпер);
  момент смены статуса — UTC-строка (SQLite datetime-формат).
"""
from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

import aiosqlite

from planner.events import log_event
from planner.programs import get_active_program
from planner.plans import get_active_plan
from planner.tz import date_to_str, day_date_for, str_to_date, today_local, utc_ts_string

__all__ = [
    "SlotsError",
    "KNOWN_MEAL_SLOTS",
    "MEAL_STATUS_VALUES",
    "extract_meal_slots",
    "create_meal_states",
    "get_today_meals",
    "set_meal_status",
    "persist_plan_bundle",
]

KNOWN_MEAL_SLOTS = ("breakfast", "lunch", "dinner", "snack")
MEAL_STATUS_VALUES = ("planned", "eaten", "skipped", "replaced", "missed")

_SLOT_ALIASES = {
    "завтрак": "breakfast",
    "обед": "lunch",
    "ужин": "dinner",
    "перекус": "snack",
    "полдник": "snack",
}


class SlotsError(ValueError):
    """Некорректный meal slot, дата или нарушение семантики meal_state."""


async def _ensure_slots_table(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS meal_state (
            id           TEXT PRIMARY KEY,
            tg_id        TEXT NOT NULL,
            plan_id      TEXT NOT NULL,
            day_date     TEXT NOT NULL,
            day_name     TEXT,
            meal_slot    TEXT NOT NULL,
            planned_ref  TEXT NOT NULL DEFAULT '{}',
            planned_text TEXT NOT NULL DEFAULT '',
            status       TEXT NOT NULL DEFAULT 'planned',
            recipe_id    TEXT,
            replace_to   TEXT,
            note         TEXT,
            status_changed_at TEXT,
            UNIQUE(plan_id, day_date, meal_slot)
        )
        """
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_meal_state_user_day ON meal_state(tg_id, day_date)"
    )


async def _ensure_bundle_tables(db: aiosqlite.Connection) -> None:
    """Идемпотентная гарантия всех 4 таблиц (модуль доступен и до init_db)."""
    from planner.programs import _ensure_pg_table
    from planner.plans import _ensure_plan_table
    from planner.events import _ensure_events_table

    await _ensure_pg_table(db)
    await _ensure_plan_table(db)
    await _ensure_slots_table(db)
    await _ensure_events_table(db)


def norm_slot(name: Any) -> str | None:
    """Канонизация названия приёма ('Завтрак'/'Breakfast' → breakfast).

    LLM может прислать русский ключ или подпись с временем — приводим к
    canonical slot; неизвестные названия возвращают None (слот не synthetic).
    """
    if not name:
        return None
    s = str(name).strip().lower()
    if not s:
        return None
    if s in _SLOT_ALIASES:
        return _SLOT_ALIASES[s]
    if s in KNOWN_MEAL_SLOTS:
        return s
    for known in KNOWN_MEAL_SLOTS:
        if known in s:
            return known
    return None


def extract_meal_slots(day: dict, day_index: int) -> list[tuple[str, dict]]:
    """Извлечь РЕАЛЬНО существующие слоты одного дня плана (PATCH-4).

    Возвращает [(slot, planned_ref)] — только слоты, фактически присутствующие
    в JSON дня с непустым значением. Никаких synthetic rows.
    """
    if not isinstance(day, dict):
        raise SlotsError(f"day[{day_index}] must be a dict")
    slots: list[tuple[str, dict]] = []
    for slot in KNOWN_MEAL_SLOTS:
        val = day.get(slot)
        if val is None:
            continue
        if isinstance(val, str) and not val.strip():
            continue
        if isinstance(val, dict) and not val:
            continue
        slots.append((slot, {"day_index": day_index, "meal": slot}))
    return slots


def _planned_text(day: dict, slot: str) -> str:
    """Денормализация названия приёма для напоминаний/замены (ADR-3)."""
    val = day.get(slot)
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, dict):
        for key in ("название", "name", "title", "meal", "dish"):
            v = val.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return json.dumps(val, ensure_ascii=False)
    return ""


async def create_meal_states(db: aiosqlite.Connection, plan: dict, days: list) -> int:
    """Создать meal_state для фактически присутствующих слотов (PATCH-4).

    day_date = plan.start_date + day_index (календарная семантика PATCH-1);
    для дня без snack snack-запись НЕ создаётся (тест 9d). Вызывать ВНУТРИ
    открытой транзакции persist-потока.
    """
    start = str_to_date(plan["start_date"])
    created = 0
    for i, day in enumerate(days):
        for slot, ref in extract_meal_slots(day, i):
            day_date = date_to_str(day_date_for(start, i))
            await db.execute(
                "INSERT OR IGNORE INTO meal_state (id, tg_id, plan_id, day_date, "
                "day_name, meal_slot, planned_ref, planned_text, status) "
                "VALUES (?,?,?,?,?,?,?,?, 'planned')",
                (
                    str(uuid.uuid4()),
                    plan["tg_id"],
                    plan["id"],
                    day_date,
                    str(day.get("day", "")),
                    slot,
                    json.dumps(ref, ensure_ascii=False),
                    _planned_text(day, slot),
                ),
            )
            created += 1
    return created


async def get_today_meals(
    db: aiosqlite.Connection,
    tg_id: str,
    today: Any = None,
    user_timezone: str | None = None,
) -> list[dict]:
    """Ответ на «что есть сегодня» — ТОЛЬКО через canonical chain (PATCH-2).

    tg_id сам по себе — недостаточный SoT: сначала активная программа, затем
    активная неделя этой программы, и только затем meal_state на дату.
    Устаревшие/replaced программы и archived недели не участвуют.
    """
    if today is None:
        today = today_local(user_timezone)
    if hasattr(today, "isoformat"):
        today_str = today.isoformat()
    else:
        today_str = str_to_date(str(today)).isoformat()

    program = await get_active_program(db, tg_id)
    if program is None:
        return []
    plan = await get_active_plan(db, program["id"], tg_id)
    if plan is None:
        return []
    cur = await db.execute(
        "SELECT * FROM meal_state WHERE plan_id=? AND day_date=? ORDER BY "
        "CASE meal_slot WHEN 'breakfast' THEN 0 WHEN 'lunch' THEN 1 "
        "WHEN 'dinner' THEN 2 ELSE 3 END",
        (plan["id"], today_str),
    )
    return [dict(r) for r in await cur.fetchall()]


async def set_meal_status(
    db: aiosqlite.Connection,
    plan_id: str,
    tg_id: str,
    day_date: str,
    meal_slot: str,
    status: str,
    *,
    replace_to: dict | None = None,
    note: str | None = None,
) -> dict | None:
    """planned → eaten/skipped/replaced/missed (writer — Phase 1; контракт здесь)."""
    if status not in MEAL_STATUS_VALUES:
        raise SlotsError(f"invalid status {status!r}")
    str_to_date(str(day_date))  # валидация формата даты
    if meal_slot not in KNOWN_MEAL_SLOTS:
        raise SlotsError(f"invalid meal_slot {meal_slot!r}")
    ts = utc_ts_string()
    try:
        await db.execute("BEGIN")
        cur = await db.execute(
            "UPDATE meal_state SET status=?, replace_to=?, note=?, status_changed_at=? "
            "WHERE plan_id=? AND tg_id=? AND day_date=? AND meal_slot=?",
            (
                status,
                json.dumps(replace_to, ensure_ascii=False) if replace_to else None,
                note,
                ts,
                plan_id,
                str(tg_id),
                str(day_date),
                meal_slot,
            ),
        )
        row = None
        if cur.rowcount == 1:
            cur2 = await db.execute(
                "SELECT * FROM meal_state WHERE plan_id=? AND tg_id=? AND "
                "day_date=? AND meal_slot=?",
                (plan_id, str(tg_id), str(day_date), meal_slot),
            )
            row = await cur2.fetchone()
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return dict(row) if row else None


async def persist_plan_bundle(
    db: aiosqlite.Connection,
    *,
    tg_id: str,
    diet_name: str,
    source: str,
    card: dict | list | None,
    constraints: dict | None,
    days: list,
    shopping_list: list | None = None,
    tips: list | None = None,
    week_no: int = 1,
    user_timezone: str | None = None,
    start_date: Any = None,
    extra_events: list[tuple[str, dict]] | None = None,
) -> dict:
    """Атомарное сохранение program+plan+meal_state+events (PATCH-5).

    ВАЖНО: вызывать ПОСЛЕ LLM-генерации и валидации (LLM вне транзакции).
    Одна короткая транзакция: program (старая active → replaced) → plan
    (старая active → archived) → meal_state (фактические слоты) → events →
    COMMIT. При ошибке — полный rollback, частичных записей не остаётся.
    """
    if not days:
        raise SlotsError("days is required (nothing to persist)")

    program_id = str(uuid.uuid4())
    plan_id = str(uuid.uuid4())
    ts = utc_ts_string()

    if start_date is None:
        start = today_local(user_timezone)
    elif hasattr(start_date, "isoformat"):
        start = start_date
    else:
        start = str_to_date(str(start_date))
    end = start + timedelta(days=6)

    try:
        await db.execute("BEGIN")
        await _ensure_bundle_tables(db)
        # 1) program: старая active → replaced (история сохраняется)
        cur = await db.execute(
            "SELECT id FROM diet_programs WHERE tg_id=? AND status='active'",
            (str(tg_id),),
        )
        old_program = await cur.fetchone()
        if old_program is not None:
            await db.execute(
                "UPDATE diet_programs SET status='replaced', completed_at=?, "
                "updated_at=? WHERE id=?",
                (ts, ts, old_program["id"]),
            )
            # активные недели заменённой программы уходят в архив (код-контроль)
            await db.execute(
                "UPDATE weekly_plans SET status='archived' "
                "WHERE program_id=? AND status='active'",
                (old_program["id"],),
            )
        await db.execute(
            "INSERT INTO diet_programs (id, tg_id, diet_name, source, card, "
            "constraints_json, status, started_at, updated_at) "
            "VALUES (?,?,?,?,?,?,'active',?,?)",
            (
                program_id,
                str(tg_id),
                str(diet_name).strip(),
                source,
                json.dumps(card or {}, ensure_ascii=False),
                json.dumps(constraints or {}, ensure_ascii=False),
                ts,
                ts,
            ),
        )
        await db.execute(
            "INSERT INTO weekly_plans (id, program_id, tg_id, week_no, start_date, "
            "end_date, days, shopping_list, tips, status, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,'active',?)",
            (
                plan_id,
                program_id,
                str(tg_id),
                int(week_no),
                date_to_str(start),
                date_to_str(end),
                json.dumps(days, ensure_ascii=False),
                json.dumps(shopping_list or [], ensure_ascii=False),
                json.dumps(tips or [], ensure_ascii=False),
                ts,
            ),
        )
        # 3) meal_state — только фактические слоты (PATCH-4)
        plan_row = {
            "id": plan_id,
            "tg_id": str(tg_id),
            "program_id": program_id,
            "start_date": date_to_str(start),
        }
        created = await create_meal_states(db, plan_row, days)
        # 4) events (Phase 0 taxonomy, §14)
        await log_event(
            db, "diet_program_created", str(tg_id),
            {"source": source, "program_id": program_id},
        )
        await log_event(
            db, "plan_created", str(tg_id),
            {"program_id": program_id, "plan_id": plan_id, "week_no": int(week_no)},
        )
        await log_event(
            db, "plan_saved", str(tg_id),
            {"program_id": program_id, "plan_id": plan_id},
        )
        for name, props in (extra_events or []):
            await log_event(db, name, str(tg_id), props)
        await db.commit()
    except aiosqlite.IntegrityError as exc:
        await db.rollback()
        raise SlotsError("integrity violation while persisting plan bundle") from exc
    except Exception:
        await db.rollback()
        raise

    return {
        "program_id": program_id,
        "plan_id": plan_id,
        "meal_states_created": created,
        "diet_name": str(diet_name).strip(),
        "start_date": date_to_str(start),
        "end_date": date_to_str(end),
    }
