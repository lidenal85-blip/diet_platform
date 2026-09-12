"""planner.events — минимальная event-инфраструктура (ADR-7, PATCH-9/10).

Контракт:
- таксономия Phase 0 (PATCH-9): ровно 7 имён событий; расширение — отдельное решение;
- политика будущих доменов (CP-2, аудит 2026-09-12): события новых доменов
  (Culinary/Fitness/Economy/Social) добавляются в эту же generic-таблицу
  аддитивными префиксами имён (``recipe_*``, ``fitness_*``, ``economy_*``,
  ``social_*``) — БЕЗ отдельных таблиц на домен. Это политика, а НЕ гарантия
  неизменности схемы: будущие Product Gates могут потребовать аддитивных
  миграций;
- ``ts`` — UTC-строка (абсолютное время, PATCH-10); «сегодня» из ts не вычисляется;
- props — JSON без чувствительных данных: health_notes/промпты/тексты сообщений
  запрещены (EventError — громкий отказ вместо молчаливой потери);
- ``log_event`` НЕ делает commit: она участвует в текущей транзакции вызывающего
  (в persist_plan_bundle — атомарно с program/plan/meal_state; при отдельном
  использовании commit делает вызывающий).
- подключение к handlers — НЕ в C-2 (только persistence-слой).
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import aiosqlite

from planner.tz import utc_ts_string

__all__ = [
    "EventError",
    "PHASE0_EVENTS",
    "FORBIDDEN_PROP_KEYS",
    "log_event",
    "recent_events",
]

PHASE0_EVENTS = frozenset(
    {
        "onboarding_started",
        "onboarding_completed",
        "diet_program_created",
        "plan_created",
        "plan_saved",
        "plan_viewed",
        "llm_call",
    }
)

# Ключи props, которые никогда не должны попадать в аналитику (PATCH-6 / §15).
FORBIDDEN_PROP_KEYS = frozenset(
    {
        "health_notes",
        "prompt",
        "message_text",
        "profile_context",
    }
)


class EventError(ValueError):
    """Недопустимое имя события или чувствительные данные в props."""


async def _ensure_events_table(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id    TEXT PRIMARY KEY,
            tg_id TEXT,
            name  TEXT NOT NULL,
            props TEXT NOT NULL DEFAULT '{}',
            ts    TEXT NOT NULL
        )
        """
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_name_ts ON events(name, ts)"
    )


async def log_event(
    db: aiosqlite.Connection,
    name: str,
    tg_id: str | None = None,
    props: dict[str, Any] | None = None,
) -> str:
    """Записать событие Phase 0 (ts = UTC). Без commit — см. докстринг модуля."""
    if name not in PHASE0_EVENTS:
        raise EventError(
            f"unknown event {name!r} (Phase 0 taxonomy: {sorted(PHASE0_EVENTS)})"
        )
    payload = dict(props or {})
    bad = FORBIDDEN_PROP_KEYS & set(payload)
    if bad:
        raise EventError(f"forbidden keys in event props: {sorted(bad)}")
    event_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO events (id, tg_id, name, props, ts) VALUES (?,?,?,?,?)",
        (
            event_id,
            str(tg_id) if tg_id else None,
            name,
            json.dumps(payload, ensure_ascii=False),
            utc_ts_string(),
        ),
    )
    return event_id


async def recent_events(
    db: aiosqlite.Connection, limit: int = 50, name: str | None = None
) -> list[dict]:
    """Последние события (ручная диагностика; чтение-аналитика — Phase 5)."""
    if name is not None:
        cur = await db.execute(
            "SELECT * FROM events WHERE name=? ORDER BY ts DESC, id LIMIT ?",
            (name, int(limit)),
        )
    else:
        cur = await db.execute(
            "SELECT * FROM events ORDER BY ts DESC, id LIMIT ?", (int(limit),)
        )
    return [dict(r) for r in await cur.fetchall()]
