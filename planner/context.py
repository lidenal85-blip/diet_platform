"""planner.context — allowlist-сборщики контекста генераторов (PATCH-6).

Три РАЗДЕЛЬНЫХ сборщика вместо одного универсального build_context():
- build_diet_context    → goal, age, activity, restrictions
- build_recipe_context  → restrictions, excluded_foods, cook_level, budget_level, max_cook_time
- build_fitness_context → activity, goal

``health_notes`` НЕ входят ни в один allowlist и никогда не покидают профиль
автоматически (если когда-либо понадобятся конкретному генератору — отдельный
ADR с явным контрактом). Не логируются; в events не попадают (events.py
отклоняет такие props). Пустые/отсутствующие поля в контекст не включаются.
"""
from __future__ import annotations

import aiosqlite

__all__ = [
    "DIET_CONTEXT_FIELDS",
    "RECIPE_CONTEXT_FIELDS",
    "FITNESS_CONTEXT_FIELDS",
    "HEALTH_NOTES_FIELD",
    "build_diet_context",
    "build_recipe_context",
    "build_fitness_context",
    "build_contexts",
]

# Документированный запрет (для тестов/аудита): вне всех allowlist'ов.
HEALTH_NOTES_FIELD = "health_notes"

DIET_CONTEXT_FIELDS = ("goal", "age", "activity", "restrictions")
RECIPE_CONTEXT_FIELDS = (
    "restrictions",
    "excluded_foods",
    "cook_level",
    "budget_level",
    "max_cook_time",
)
FITNESS_CONTEXT_FIELDS = ("activity", "goal")


async def _fetch_profile(db: aiosqlite.Connection, tg_id: str) -> dict:
    """Один SELECT * — далее allowlist-отбор (нет SELECT с перечислением колонок,
    которых может не быть на старых БД; лишние поля никогда не читаются)."""
    cur = await db.execute(
        "SELECT * FROM user_profiles WHERE tg_id=?", (str(tg_id),)
    )
    row = await cur.fetchone()
    return dict(row) if row else {}


def _pick(profile: dict, fields) -> dict:
    out: dict = {}
    for field in fields:
        val = profile.get(field)
        if val is None:
            continue
        if isinstance(val, str) and not val.strip():
            continue
        out[field] = val
    return out


async def build_diet_context(db: aiosqlite.Connection, tg_id: str) -> dict:
    """Контекст diet/plan-генератора (allowlist PATCH-6)."""
    return _pick(await _fetch_profile(db, tg_id), DIET_CONTEXT_FIELDS)


async def build_recipe_context(db: aiosqlite.Connection, tg_id: str) -> dict:
    """Контекст recipe-генератора (allowlist PATCH-6)."""
    return _pick(await _fetch_profile(db, tg_id), RECIPE_CONTEXT_FIELDS)


async def build_fitness_context(db: aiosqlite.Connection, tg_id: str) -> dict:
    """Контекст fitness-генератора (allowlist PATCH-6)."""
    return _pick(await _fetch_profile(db, tg_id), FITNESS_CONTEXT_FIELDS)


async def build_contexts(db: aiosqlite.Connection, tg_id: str) -> dict:
    """Все три контекста одной точкой чтения (каждый — свой allowlist)."""
    profile = await _fetch_profile(db, tg_id)
    return {
        "diet": _pick(profile, DIET_CONTEXT_FIELDS),
        "recipe": _pick(profile, RECIPE_CONTEXT_FIELDS),
        "fitness": _pick(profile, FITNESS_CONTEXT_FIELDS),
    }
