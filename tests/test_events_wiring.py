"""C-3 Commit 5 tests: §20 step 7 (bot-side §14 points) + step 8 (E2E-инварианты).

Test-first: RED до реализации. Покрытие:
1. btn_pick_diet пишет onboarding_started — собственная попытка,
   сбой аналитики не ломает пользовательский флоу;
2. got_activity пишет onboarding_completed ПОСЛЕ commit профиля —
   сбой записи события не откатывает upsert (профиль остаётся сохранён);
3. chose_diet добавляет plan_viewed атомарно с bundle через
   persist_plan_bundle(extra_events=[...]);
4. Инварианты §20-8 после chose_diet: активная программа, календарная неделя
   (end-start == 6 дней), meal_state только по фактическим слотам (7×3),
   canonical chain get_today_meals отвечает на «что есть сегодня».

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
import planner
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
    db_file = tmp_path / "c3_events_test.db"
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


def _make_message(uid: int = 888) -> MagicMock:
    msg = MagicMock()
    msg.from_user.id = uid
    msg.answer = AsyncMock(return_value=MagicMock())
    msg.delete = AsyncMock(return_value=MagicMock())  # chose_diet удаляет "часы"-сообщение
    return msg


def _make_state(data: dict) -> MagicMock:
    state = MagicMock()
    state.get_data = AsyncMock(return_value=dict(data))
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


PROFILE = {"goal": "Похудеть", "age": 30,
           "restrictions": "Без глютена", "activity": "Силовые 3р/нед"}

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


# ── 1. btn_pick_diet → onboarding_started (own-try) ─────────────────────────

async def test_btn_pick_diet_logs_onboarding_started(db):
    msg = _make_message()
    state = _make_state({})

    await dp.btn_pick_diet(msg, state)

    # пользовательский флоу цел
    assert state.set_state.await_count >= 1
    assert msg.answer.await_count >= 1

    rows = await _fetch_all(db, "SELECT name FROM events WHERE tg_id='888'")
    names = {r["name"] for r in rows}
    assert "onboarding_started" in names


# ── 2. got_activity → onboarding_completed после commit профиля ─────────────

async def test_got_activity_logs_onboarding_completed(db):
    msg = _make_message()
    msg.text = "Силовые 3р/нед"
    state = _make_state(PROFILE)

    await dp.got_activity(msg, state)

    rows = await _fetch_all(db, "SELECT name FROM events WHERE tg_id='888'")
    assert "onboarding_completed" in {r["name"] for r in rows}
    # профиль при этом сохранён (upsert из Commit 1)
    prof = await _fetch_all(db, "SELECT onboarding_done FROM user_profiles WHERE tg_id='888'")
    assert len(prof) == 1 and prof[0]["onboarding_done"] == 1


async def test_event_failure_does_not_rollback_profile(db, monkeypatch):
    """Own-try контракт: сбой log_event не ломает флоу и не откатывает upsert."""

    async def boom(*args, **kwargs):
        raise RuntimeError("events down")

    monkeypatch.setattr(planner, "log_event", boom)

    msg = _make_message()
    msg.text = "Силовые 3р/нед"
    state = _make_state(PROFILE)

    await dp.got_activity(msg, state)  # не должен бросить

    prof = await _fetch_all(db, "SELECT onboarding_done FROM user_profiles WHERE tg_id='888'")
    assert len(prof) == 1 and prof[0]["onboarding_done"] == 1


# ── 3. chose_diet → plan_viewed атомарно с bundle ────────────────────────────

async def test_chose_diet_logs_plan_viewed(db, monkeypatch):
    msg = _make_message()
    msg.text = "1️⃣ Диета A"
    state = _make_state({**PROFILE, "diets": [{"name": "Диета A"}]})

    async def fake_plan(diet_name, data):
        return json.loads(json.dumps(PLAN))

    monkeypatch.setattr(dp, "_get_week_plan", fake_plan)

    await dp.chose_diet(msg, state)

    events = await _fetch_all(db, "SELECT name, props FROM events WHERE tg_id='888'")
    names = {r["name"] for r in events}
    assert {"diet_program_created", "plan_created", "plan_saved"} <= names  # bundle (Commit 1)
    assert "plan_viewed" in names                                            # RED: §20-7
    viewed = [r for r in events if r["name"] == "plan_viewed"]
    assert len(viewed) == 1


# ── 4. Инварианты §20-8 (исполняемая спека для E2E) ──────────────────────────

async def test_step8_invariants_after_chose_diet(db, monkeypatch):
    msg = _make_message()
    msg.text = "1️⃣ Диета A"
    state = _make_state({**PROFILE, "diets": [{"name": "Диета A"}]})

    async def fake_plan(diet_name, data):
        return json.loads(json.dumps(PLAN))

    monkeypatch.setattr(dp, "_get_week_plan", fake_plan)
    await dp.chose_diet(msg, state)

    # 1) активная программа
    progs = await _fetch_all(db, "SELECT * FROM diet_programs WHERE tg_id='888'")
    assert len(progs) == 1 and progs[0]["status"] == "active"

    # 2) активный план: календарная неделя (PATCH-1)
    plans = await _fetch_all(db, "SELECT * FROM weekly_plans WHERE tg_id='888'")
    assert len(plans) == 1 and plans[0]["status"] == "active"
    start = date.fromisoformat(plans[0]["start_date"])
    end = date.fromisoformat(plans[0]["end_date"])
    assert (end - start).days == 6

    # 3) meal_state: только фактические слоты (PATCH-4: 7×3, без синтетики)
    meals = await _fetch_all(db, "SELECT meal_slot FROM meal_state WHERE tg_id='888'")
    assert len(meals) == 21
    assert {m["meal_slot"] for m in meals} == {"breakfast", "lunch", "dinner"}

    # 4) canonical chain (PATCH-2): «что есть сегодня» отвечает через
    #    program → plan → meal_state(plan_id, day_date=today)
    async with aiosqlite.connect(str(db)) as conn:
        conn.row_factory = aiosqlite.Row
        today_meals = await planner.get_today_meals(conn, "888")
    assert len(today_meals) == 3
    assert {m["meal_slot"] for m in today_meals} == {"breakfast", "lunch", "dinner"}
