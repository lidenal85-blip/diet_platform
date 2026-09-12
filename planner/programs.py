"""planner.programs — diet_programs (ADR-1): пользовательская программа питания.

Инвариант PATCH-3 (обязателен): у пользователя не более одной
``status='active'`` программы — физическая линия: partial unique index
``idx_one_active_program_per_user``; кодовая линия: явная проверка перед INSERT.
Целостность и код, и БД (ни одна линия не удаляется).

``constraints_json`` — снимок контекста выбора (выход build_diet_context,
без health_notes — PATCH-6); «паспорт» для адаптации Phase 2.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import aiosqlite

from planner.tz import utc_ts_string

__all__ = [
    "ProgramError",
    "create_program",
    "get_active_program",
    "get_program",
    "pause_program",
    "resume_program",
    "complete_program",
    "replace_program",
    "list_programs",
]

PROGRAM_STATUSES = ("active", "paused", "completed", "replaced")


class ProgramError(ValueError):
    """Некорректный lifecycle-переход или аргументы программы."""


async def _ensure_pg_table(db: aiosqlite.Connection) -> None:
    """Гарантия наличия таблицы (идемпотентно) — модуль может создаваться до init_db."""
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS diet_programs (
            id          TEXT PRIMARY KEY,
            tg_id       TEXT NOT NULL,
            diet_name   TEXT NOT NULL,
            source      TEXT NOT NULL DEFAULT 'llm',
            card        TEXT NOT NULL DEFAULT '{}',
            constraints_json TEXT NOT NULL DEFAULT '{}',
            status      TEXT NOT NULL DEFAULT 'active',
            started_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT
        )
        """
    )
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_program_per_user "
        "ON diet_programs(tg_id) WHERE status = 'active'"
    )


async def create_program(
    db: aiosqlite.Connection,
    tg_id: str,
    diet_name: str,
    source: str = "llm",
    card: dict | list | None = None,
    constraints: dict | None = None,
) -> dict:
    """Создать программу; если есть активная — пометить её ``replaced``.

    Все записи — в одной транзакции (данные уже валидированы, LLM тут нет —
    PATCH-5: транзакция короткая и не накрывает внешние вызовы).
    """
    if not tg_id:
        raise ProgramError("tg_id is required")
    if not diet_name or not str(diet_name).strip():
        raise ProgramError("diet_name is required")
    if source not in ("llm", "heuristic", "registry"):
        raise ProgramError(f"invalid source {source!r}")

    tg_id = str(tg_id)
    program_id = str(uuid.uuid4())
    card_json = json.dumps(card or {}, ensure_ascii=False)
    constraints_json = json.dumps(constraints or {}, ensure_ascii=False)
    ts = utc_ts_string()

    try:
        await db.execute("BEGIN")
        await _ensure_pg_table(db)
        cur = await db.execute(
            "SELECT id FROM diet_programs WHERE tg_id=? AND status='active'",
            (tg_id,),
        )
        old = await cur.fetchone()
        if old is not None:
            await db.execute(
                "UPDATE diet_programs SET status='replaced', completed_at=?, "
                "updated_at=? WHERE id=?",
                (ts, ts, old["id"]),
            )
            # активная неделя заменённой программы уходит в архив (код-контроль, без FK)
            from planner.plans import _ensure_plan_table

            await _ensure_plan_table(db)
            await db.execute(
                "UPDATE weekly_plans SET status='archived' "
                "WHERE program_id=? AND status='active'",
                (old["id"],),
            )
        await db.execute(
            "INSERT INTO diet_programs (id, tg_id, diet_name, source, card, "
            "constraints_json, status, started_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (program_id, tg_id, str(diet_name).strip(), source,
             card_json, constraints_json, "active", ts, ts),
        )
        await db.commit()
    except aiosqlite.IntegrityError as exc:
        await db.rollback()
        # физическая линия защиты — partial unique index
        raise ProgramError(
            "active program already exists for this user (DB invariant)"
        ) from exc
    except Exception:
        await db.rollback()
        raise

    return await get_program(db, program_id, tg_id)


async def get_program(db: aiosqlite.Connection, program_id: str, tg_id: str) -> dict | None:
    """Одна программа; ownership: tg_id обязателен в WHERE (§24 FM-10)."""
    cur = await db.execute(
        "SELECT * FROM diet_programs WHERE id=? AND tg_id=?",
        (program_id, str(tg_id)),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_active_program(db: aiosqlite.Connection, tg_id: str) -> dict | None:
    """Активная программа пользователя — первое звено canonical chain (PATCH-2)."""
    cur = await db.execute(
        "SELECT * FROM diet_programs WHERE tg_id=? AND status='active'",
        (str(tg_id),),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def list_programs(db: aiosqlite.Connection, tg_id: str) -> list[dict]:
    """История программ (новые сверху)."""
    cur = await db.execute(
        "SELECT * FROM diet_programs WHERE tg_id=? ORDER BY started_at DESC, id",
        (str(tg_id),),
    )
    return [dict(r) for r in await cur.fetchall()]


async def _transition_status(
    db: aiosqlite.Connection,
    program_id: str,
    tg_id: str,
    from_status: str,
    to_status: str,
    set_completed_at: bool = False,
) -> dict | None:
    ts = utc_ts_string()
    try:
        await db.execute("BEGIN")
        completed = ts if set_completed_at else None
        if set_completed_at:
            cur = await db.execute(
                "UPDATE diet_programs SET status=?, updated_at=?, completed_at=? "
                "WHERE id=? AND tg_id=? AND status=?",
                (to_status, ts, completed, program_id, str(tg_id), from_status),
            )
        else:
            cur = await db.execute(
                "UPDATE diet_programs SET status=?, updated_at=? "
                "WHERE id=? AND tg_id=? AND status=?",
                (to_status, ts, program_id, str(tg_id), from_status),
            )
        if cur.rowcount != 1:
            await db.rollback()
            return None
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return await get_program(db, program_id, tg_id)


async def pause_program(db: aiosqlite.Connection, program_id: str, tg_id: str) -> dict | None:
    """active → paused."""
    return await _transition_status(db, program_id, tg_id, "active", "paused")


async def resume_program(db: aiosqlite.Connection, program_id: str, tg_id: str) -> dict | None:
    """paused → active (может нарушить инвариант, если появилась другая active)."""
    try:
        result = await _transition_status(db, program_id, tg_id, "paused", "active")
    except aiosqlite.IntegrityError as exc:
        raise ProgramError(
            "cannot resume: another active program exists for this user"
        ) from exc
    return result


async def complete_program(db: aiosqlite.Connection, program_id: str, tg_id: str) -> dict | None:
    """active → completed (ставит completed_at)."""
    return await _transition_status(
        db, program_id, tg_id, "active", "completed", set_completed_at=True
    )


async def replace_program(db: aiosqlite.Connection, program_id: str, tg_id: str) -> dict | None:
    """active → replaced (история сохраняется; новая программа создаётся через create_program)."""
    return await _transition_status(
        db, program_id, tg_id, "active", "replaced", set_completed_at=True
    )
