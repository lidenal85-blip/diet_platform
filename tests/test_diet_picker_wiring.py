"""C-3 Commit 1 tests: §20 step 3 — diet_picker EXTEND (promts/4.md §20-3).

Test-first: RED до реализации. Покрытие:
1. got_activity сохраняет restrictions + activity в СУЩЕСТВУЮЩЕМ upsert
   (контракт единого писателя профиля, §10);
2. chose_diet после успешного плана атомарно сохраняет
   program+plan+meal_state+events через persist_plan_bundle (LLM вне TX);
3. chose_diet при ошибке генерации плана НЕ трогает новые таблицы
   (частичных записей нет — PATCH-5), пользователь получает сообщение.

Тесты выполняются на temp-БД (monkeypatch DB_PATH) — прод-БД не используется
(§16 Production Safety).
"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest
import pytest_asyncio

import database
from bot_handlers import diet_picker as dp

pytestmark = pytest.mark.asyncio


# ── Fixture: temp DB via real init_db + patched DB_PATH copies ──────────────

async def _add_prod_columns(db_file: str) -> None:
    """Колонки, которые в проде создают runtime-ALTER'ы хендлеров
    (puhlyash_settings/cabinet): отражаем фактическую схему прода."""
    async with aiosqlite.connect(str(db_file)) as conn:
        for col in ("cook_level TEXT", "budget_level TEXT", "max_cook_time INTEGER",
                    "active_diet_mode TEXT"):
            try:
                await conn.execute(f"ALTER TABLE user_profiles ADD COLUMN {col}")
            except Exception:
                pass
        await conn.commit()


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    db_file = tmp_path / "c3_wiring_test.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    # diet_picker импортирует DB_PATH по значению — патчим и его копию
    monkeypatch.setattr(dp, "DB_PATH", str(db_file))
    await database.init_db()
    await _add_prod_columns(str(db_file))
    return db_file


async def _fetch_all(db_file: str, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
    async with aiosqlite.connect(str(db_file)) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(sql, params)
        return await cur.fetchall()


def _make_message(uid: int = 777) -> MagicMock:
    msg = MagicMock()
    msg.from_user.id = uid
    msg.answer = AsyncMock(return_value=MagicMock())
    return msg


def _make_state(data: dict) -> MagicMock:
    state = MagicMock()
    state.get_data = AsyncMock(return_value=dict(data))
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


PROFILE = {"goal": "Похудеть", "age": 30, "restrictions": "Без глютена", "activity": "Силовые 3р/нед"}

PLAN = {
    "days": [
        {
            "day": f"День {i + 1}",
            "breakfast": {"название": "Овсянка", "ккал": 300},
            "lunch": {"название": "Курица с рисом", "ккал": 500},
            "dinner": {"название": "Салат", "ккал": 350},
        }
        for i in range(7)
    ],
    "shopping_list": ["гречка"],
    "tips": ["Пей воду"],
}


# ── 1. Профиль: единый писатель (got_activity) ──────────────────────────────

async def test_got_activity_persists_restrictions_and_activity(db):
    msg = _make_message()
    msg.text = "Силовые 3р/нед"
    state = _make_state(PROFILE)

    await dp.got_activity(msg, state)

    rows = await _fetch_all(
        db,
        "SELECT goal, age, restrictions, activity, onboarding_done "
        "FROM user_profiles WHERE tg_id='777'",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["goal"] == "Похудеть"
    assert row["age"] == 30
    assert row["restrictions"] == "Без глютена"
    assert row["activity"] == "Силовые 3р/нед"
    assert row["onboarding_done"] == 1


# ── 2. chose_diet: атомарный bundle после успешного плана ───────────────────

async def test_chose_diet_persists_bundle(db, monkeypatch):
    msg = _make_message()
    msg.text = "1️⃣ Диета A"
    state = _make_state({**PROFILE, "diets": [{"name": "Диета A"}]})

    async def fake_plan(diet_name, data):
        return json.loads(json.dumps(PLAN))

    monkeypatch.setattr(dp, "_get_week_plan", fake_plan)

    await dp.chose_diet(msg, state)

    progs = await _fetch_all(db, "SELECT * FROM diet_programs WHERE tg_id='777'")
    assert len(progs) == 1
    assert progs[0]["status"] == "active"
    assert progs[0]["diet_name"] == "Диета A"

    plans = await _fetch_all(db, "SELECT * FROM weekly_plans WHERE tg_id='777'")
    assert len(plans) == 1
    assert plans[0]["status"] == "active"
    assert plans[0]["program_id"] == progs[0]["id"]
    start = date.fromisoformat(plans[0]["start_date"])
    end = date.fromisoformat(plans[0]["end_date"])
    assert (end - start).days == 6  # PATCH-1: календарная неделя
    assert len(json.loads(plans[0]["days"])) == 7

    meals = await _fetch_all(db, "SELECT * FROM meal_state WHERE tg_id='777'")
    assert len(meals) == 7 * 3  # PATCH-4: только фактические слоты (7×3, без snack)
    assert all(m["plan_id"] == plans[0]["id"] for m in meals)

    events = await _fetch_all(db, "SELECT name FROM events WHERE tg_id='777'")
    names = {r["name"] for r in events}
    assert {"diet_program_created", "plan_created", "plan_saved"} <= names


# ── 3. chose_diet: LLM/генерация упала → БД не тронута ──────────────────────

async def test_chose_diet_failure_leaves_new_tables_untouched(db, monkeypatch):
    msg = _make_message()
    msg.text = "1️⃣ Диета A"
    state = _make_state({**PROFILE, "diets": [{"name": "Диета A"}]})

    async def boom(diet_name, data):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(dp, "_get_week_plan", boom)

    # хендлер не должен бросать исключение наружу (user-facing catch)
    await dp.chose_diet(msg, state)

    for table in ("diet_programs", "weekly_plans", "meal_state", "events"):
        rows = await _fetch_all(db, f"SELECT * FROM {table} WHERE tg_id='777'")
        assert rows == [], f"{table} must be untouched after plan failure"

    # пользователь получил сообщение об ошибке
    texts = [c.args[0] for c in msg.answer.call_args_list if c.args]
    assert any("Ошибка плана" in t for t in texts)
