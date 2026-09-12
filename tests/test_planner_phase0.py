"""C-2 tests: planner module + Phase 0 schema (promts/4.md §15).

Покрытие: идемпотентность init_db, 4 таблицы, 3 колонки, оба partial unique
index, canonical chain, календарные границы, meal_state только по фактическим
слотам, allowlist-контексты, event-таксономия, атомарность persist_plan_bundle.

Тесты выполняются на temp-БД (monkeypatch database.DB_PATH) — прод-БД не
используется (§16 Production Safety).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import aiosqlite
import pytest
import pytest_asyncio

import database

pytestmark = pytest.mark.asyncio
from planner import (
    EventError,
    ProgramError,
    PlanError,
    SlotsError,
    build_contexts,
    create_meal_states,
    create_plan,
    create_program,
    get_active_plan,
    get_active_program,
    get_program,
    get_today_meals,
    log_event,
    persist_plan_bundle,
    resume_program,
    to_local_date,
    today_local,
    week_bounds,
)


# ── Fixture: temp DB via real init_db (idempotent path) ────────────────────

@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase0_test.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    await database.init_db()
    async with aiosqlite.connect(str(db_file)) as conn:
        conn.row_factory = aiosqlite.Row
        # колонки, которые в проде добавляют runtime-ALTER'ы хендлеров
        # (cabinet/puhlyash_settings): отражаем фактическую схему прода
        for col in ("cook_level TEXT", "budget_level TEXT", "max_cook_time INTEGER"):
            try:
                await conn.execute(f"ALTER TABLE user_profiles ADD COLUMN {col}")
            except Exception:
                pass
        await conn.commit()
        yield conn


async def _add_profile(db, tg_id, **fields):
    cols = ", ".join(["tg_id"] + list(fields))
    marks = ", ".join(["?"] * (1 + len(fields)))
    await db.execute(
        f"INSERT INTO user_profiles ({cols}) VALUES ({marks})",
        (tg_id, *fields.values()),
    )
    await db.commit()


DAYS_MIXED = [
    {  # 4 слота
        "day": "Понедельник",
        "breakfast": "Овсянка с ягодами",
        "lunch": "Курица с рисом",
        "dinner": "Творог с овощами",
        "snack": "Горсть миндаля",
    },
    {  # 3 слота — snack отсутствует
        "day": "Вторник",
        "breakfast": "Омлет",
        "lunch": "Гречка с рыбой",
        "dinner": "Салат с тунцом",
    },
    {  # пустой snack — не считается слотом (PATCH-4)
        "day": "Среда",
        "breakfast": "Сырники",
        "lunch": "Суп-пюре",
        "dinner": "Запечённая индейка",
        "snack": "",
    },
    {  # snack объектом — реальный формат LLM
        "day": "Четверг",
        "breakfast": "Каша",
        "lunch": "Плов",
        "dinner": "Овощное рагу",
        "snack": {"название": "Йогурт", "ккал": 150},
    },
]


async def _bundle(db, tg_id, diet="Средиземноморская диета", days=None, tz=None):
    return await persist_plan_bundle(
        db,
        tg_id=tg_id,
        diet_name=diet,
        source="llm",
        card={"name": diet},
        constraints={"goal": "похудеть"},
        days=days if days is not None else DAYS_MIXED,
        shopping_list=[{"item": "овсянка"}],
        tips=["пить воду"],
        user_timezone=tz,
    )


# ── Schema ──────────────────────────────────────────────────────────────────

class TestSchema:
    async def test_init_db_idempotent(self, db, tmp_path, monkeypatch):
        await _add_profile(db, "1")
        await database.init_db()  # повторный запуск
        await database.init_db()  # и ещё раз
        cur = await db.execute("SELECT COUNT(*) FROM user_profiles")
        assert (await cur.fetchone())[0] == 1  # данные целы, дублей нет
        cur = await db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name IN ('diet_programs','weekly_plans','meal_state','events')"
        )
        assert (await cur.fetchone())[0] == 4

    async def test_new_tables_exist(self, db):
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        names = {r[0] for r in await cur.fetchall()}
        assert {"diet_programs", "weekly_plans", "meal_state", "events"} <= names

    async def test_profile_columns_exist(self, db):
        cur = await db.execute("PRAGMA table_info(user_profiles)")
        cols = {r["name"] for r in await cur.fetchall()}
        assert {"restrictions", "activity", "timezone"} <= cols

    async def test_timezone_default_fallback(self, db):
        await _add_profile(db, "tz-default-user", goal="похудеть")
        cur = await db.execute(
            "SELECT timezone FROM user_profiles WHERE tg_id='tz-default-user'"
        )
        assert (await cur.fetchone())["timezone"] == "Europe/Moscow"

    async def test_partial_unique_indexes_exist(self, db):
        cur = await db.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND name IN "
            "('idx_one_active_program_per_user','idx_one_active_plan_per_program')"
        )
        rows = {r["name"]: r["sql"] for r in await cur.fetchall()}
        assert set(rows) == {
            "idx_one_active_program_per_user",
            "idx_one_active_plan_per_program",
        }
        for sql in rows.values():
            assert "UNIQUE" in (sql or "").upper()
            assert "WHERE" in (sql or "").upper() and "status = 'active'" in (sql or "")

    async def test_second_active_program_same_user_integrity_error(self, db):
        tg = "111"
        await _add_profile(db, tg)
        p_a = await create_program(db, tg, "Диета A")
        p_a_id = p_a["id"]
        # физическая линия защиты: вторая active тому же tg_id отклоняется БД
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "INSERT INTO diet_programs (id, tg_id, diet_name, status) VALUES (?,?,?,'active')",
                (str(uuid.uuid4()), tg, "Диета B"),
            )
            await db.commit()
        await db.rollback()  # снять auto-транзакцию после IntegrityError
        # кодовая линия (safety net): resume paused-программы при живой другой
        # active → IntegrityError обёрнут в ProgramError (не тихая порча)
        paused_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO diet_programs (id, tg_id, diet_name, status) VALUES (?,?,?,'paused')",
            (paused_id, tg, "Диета Paused"),
        )
        await db.commit()
        with pytest.raises(ProgramError):
            await resume_program(db, paused_id, tg)
        # replace-семантика create_program: инвариант не нарушается, история цела
        p_c = await create_program(db, tg, "Диета C")
        assert p_c["status"] == "active"
        assert (await get_program(db, p_a_id, tg))["status"] == "replaced"

    async def test_second_active_plan_same_program_integrity_error(self, db):
        tg, pid = "222", str(uuid.uuid4())
        await _add_profile(db, tg)
        await db.execute(
            "INSERT INTO diet_programs (id, tg_id, diet_name, status) VALUES (?,?,?,'active')",
            (pid, tg, "Диета"),
        )
        await db.execute(
            "INSERT INTO weekly_plans (id, program_id, tg_id, start_date, end_date, status) "
            "VALUES (?,?,?,?,?,'active')",
            (str(uuid.uuid4()), pid, tg, "2026-09-07", "2026-09-13"),
        )
        await db.commit()
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "INSERT INTO weekly_plans (id, program_id, tg_id, start_date, end_date, status) "
                "VALUES (?,?,?,?,?,'active')",
                (str(uuid.uuid4()), pid, tg, "2026-09-14", "2026-09-20"),
            )
            await db.commit()
        await db.rollback()  # снять auto-транзакцию после IntegrityError
        # кодовая линия: create_plan архивирует старую active и создаёт новую —
        # инвариант не нарушается (replace-семантика), дублей active нет
        plan2 = await create_plan(db, pid, tg, start_date="2026-09-14")
        assert plan2["status"] == "active"
        cur = await db.execute(
            "SELECT COUNT(*) FROM weekly_plans WHERE program_id=? AND status='active'",
            (pid,),
        )
        assert (await cur.fetchone())[0] == 1

    async def test_active_program_other_user_allowed(self, db):
        await _add_profile(db, "A1")
        await _add_profile(db, "B1")
        p1 = await create_program(db, "A1", "Диета A")
        p2 = await create_program(db, "B1", "Диета B")
        assert p1["status"] == "active" and p2["status"] == "active"

    async def test_active_plan_other_program_allowed(self, db):
        tg1, tg2 = "333", "334"
        await _add_profile(db, tg1)
        await _add_profile(db, tg2)
        p1 = await create_program(db, tg1, "Диета 1")
        p2 = await create_program(db, tg2, "Диета 2")
        plan1 = await create_plan(db, p1["id"], tg1, start_date="2026-09-07")
        plan2 = await create_plan(db, p2["id"], tg2, start_date="2026-09-07")
        assert plan1["status"] == "active" and plan2["status"] == "active"


# ── Canonical chain ─────────────────────────────────────────────────────────

class TestCanonicalChain:
    async def test_chain_returns_today_meals(self, db):
        tg = "400"
        await _add_profile(db, tg)
        await _bundle(db, tg)
        meals = await get_today_meals(db, tg)
        assert len(meals) == 4  # понедельник = день 0: 4 фактических слота
        slots = [m["meal_slot"] for m in meals]
        assert slots == ["breakfast", "lunch", "dinner", "snack"]
        assert all(m["status"] == "planned" for m in meals)

    async def test_replaced_program_not_source(self, db):
        tg = "401"
        await _add_profile(db, tg)
        first = await _bundle(db, tg, diet="Диета 1")
        second = await _bundle(db, tg, diet="Диета 2")
        old_program = await get_active_program(db, tg)
        assert old_program["id"] == second["program_id"]
        # старые данные в БД остались (история), но chain их не отдаёт:
        cur = await db.execute(
            "SELECT COUNT(*) FROM meal_state WHERE plan_id=?", (first["plan_id"],)
        )
        assert (await cur.fetchone())[0] > 0
        meals = await get_today_meals(db, tg)
        assert all(m["plan_id"] == second["plan_id"] for m in meals)

    async def test_archived_plan_not_source(self, db):
        tg = "402"
        await _add_profile(db, tg)
        await _bundle(db, tg)
        program = await get_active_program(db, tg)
        from planner import archive_plan
        await archive_plan(db, (await get_active_plan(db, program["id"], tg))["id"], tg)
        await create_plan(db, program["id"], tg, days=[], start_date="2026-09-07")
        assert await get_today_meals(db, tg) == []

    async def test_no_active_program_empty(self, db):
        await _add_profile(db, "403")
        assert await get_today_meals(db, "403") == []
        assert await get_today_meals(db, "нет-такого-юзера") == []

    async def test_no_active_plan_empty(self, db):
        tg = "404"
        await _add_profile(db, tg)
        await create_program(db, tg, "Диета без плана")
        assert await get_today_meals(db, tg) == []


# ── Dates / timezone ────────────────────────────────────────────────────────

class TestDates:
    async def test_end_is_start_plus_six(self, db):
        tg = "500"
        await _add_profile(db, tg)
        await _bundle(db, tg)
        program = await get_active_program(db, tg)
        plan = await get_active_plan(db, program["id"], tg)
        from planner.tz import str_to_date, week_bounds as wb
        start, end = str_to_date(plan["start_date"]), str_to_date(plan["end_date"])
        assert wb(start) == (start, end)
        assert (end - start).days == 6

    async def test_invalid_week_bounds_rejected(self, db):
        tg = "501"
        await _add_profile(db, tg)
        pid = str(uuid.uuid4())
        await create_program(db, tg, "Диета")
        with pytest.raises(PlanError):
            await create_plan(db, pid, tg, start_date="2026-09-07", end_date="2026-09-12")

    async def test_day_date_calculation(self, db):
        tg = "502"
        await _add_profile(db, tg)
        result = await _bundle(db, tg)
        from planner.tz import str_to_date
        start = str_to_date(result["start_date"])
        cur = await db.execute(
            "SELECT day_date, planned_ref FROM meal_state WHERE plan_id=?",
            (result["plan_id"],),
        )
        rows = await cur.fetchall()
        import json as _json
        for r in rows:
            ref = _json.loads(r["planned_ref"])
            expected = start.toordinal() + ref["day_index"]
            from datetime import date as _date
            assert str_to_date(r["day_date"]).toordinal() == expected

    async def test_timezone_local_date(self):
        # 2026-09-12 21:30 UTC = 2026-09-13 00:30 MSK → локальная дата уже следующая
        moment = datetime(2026, 9, 12, 21, 30, tzinfo=timezone.utc)
        assert to_local_date(moment, "Europe/Moscow").isoformat() == "2026-09-13"
        assert to_local_date(moment, "UTC").isoformat() == "2026-09-12"
        assert today_local("Europe/Moscow").isoformat()  # не падает, формат ISO


# ── Meal slots (PATCH-4) ────────────────────────────────────────────────────

class TestMealSlots:
    async def test_only_actual_slots(self, db):
        tg = "600"
        await _add_profile(db, tg)
        result = await _bundle(db, tg)
        cur = await db.execute(
            "SELECT day_date, meal_slot FROM meal_state WHERE plan_id=?",
            (result["plan_id"],),
        )
        rows = await cur.fetchall()
        assert len(rows) == 4 + 3 + 3 + 4  # по каждому дню — только реальные слоты
        by_day: dict[str, set] = {}
        for r in rows:
            by_day.setdefault(r["day_date"], set()).add(r["meal_slot"])
        counts = sorted(len(v) for v in by_day.values())
        assert counts == [3, 3, 4, 4]

    async def test_no_synthetic_snack(self, db):
        tg = "601"
        await _add_profile(db, tg)
        result = await _bundle(db, tg)
        cur = await db.execute(
            "SELECT meal_slot FROM meal_state WHERE plan_id=? AND meal_slot='snack'",
            (result["plan_id"],),
        )
        snack_rows = await cur.fetchall()
        assert len(snack_rows) == 2  # snack реально есть только в днях 0 и 3

    async def test_unique_slot_constraint(self, db):
        tg = "602"
        await _add_profile(db, tg)
        result = await _bundle(db, tg)
        cur = await db.execute(
            "SELECT day_date, meal_slot FROM meal_state WHERE plan_id=? LIMIT 1",
            (result["plan_id"],),
        )
        day_date, slot = (await cur.fetchone())
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "INSERT INTO meal_state (id, tg_id, plan_id, day_date, meal_slot) "
                "VALUES (?,?,?,?,?)",
                (str(uuid.uuid4()), tg, result["plan_id"], day_date, slot),
            )
            await db.commit()
        await db.rollback()  # снять auto-транзакцию после IntegrityError

    async def test_extract_rejects_non_dict_day(self):
        with pytest.raises(SlotsError):
            from planner import extract_meal_slots
            extract_meal_slots("мусор", 0)  # type: ignore[arg-type]


# ── Context allowlists (PATCH-6) ────────────────────────────────────────────

class TestContext:
    async def test_allowlists_separated(self, db):
        await _add_profile(
            db, "700",
            goal="похудеть", age=30, activity="moderate", restrictions="без свинины",
            excluded_foods='["грибы"]', cook_level="simple", budget_level="medium",
            max_cook_time=30, health_notes="аллергия на орехи",
        )
        ctx = await build_contexts(db, "700")
        assert set(ctx["diet"]) == {"goal", "age", "activity", "restrictions"}
        assert set(ctx["recipe"]) == {
            "restrictions", "excluded_foods", "cook_level", "budget_level", "max_cook_time",
        }
        assert set(ctx["fitness"]) == {"activity", "goal"}

    async def test_health_notes_never_leak(self, db):
        await _add_profile(
            db, "701", goal="набрать", health_notes="СЕКРЕТНЫЕ МЕДИЦИНСКИЕ ДАННЫЕ",
        )
        ctx = await build_contexts(db, "701")
        blob = repr(ctx)
        assert "СЕКРЕТНЫЕ МЕДИЦИНСКИЕ ДАННЫЕ" not in blob
        assert "health_notes" not in blob

    async def test_empty_fields_omitted(self, db):
        await _add_profile(db, "702", goal="")
        ctx = await build_contexts(db, "702")
        assert "goal" not in ctx["diet"]  # пустые поля не включаются

    async def test_health_notes_never_in_events(self, db):
        with pytest.raises(EventError):
            await log_event(db, "plan_viewed", "703", {"health_notes": "секрет"})
        cur = await db.execute("SELECT COUNT(*) FROM events")
        assert (await cur.fetchone())[0] == 0  # громкий отказ, ничего не записано


# ── Events (PATCH-9/10) ─────────────────────────────────────────────────────

class TestEvents:
    async def test_taxonomy_enforced(self, db):
        await log_event(db, "plan_viewed", "800")
        with pytest.raises(EventError):
            await log_event(db, "made_up_event", "800")

    async def test_ts_is_utc_format(self, db):
        await log_event(db, "plan_viewed", "801", {"program_id": "p1"})
        cur = await db.execute("SELECT ts FROM events WHERE tg_id='801'")
        ts = (await cur.fetchone())["ts"]
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", ts)
        parsed = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        assert abs((now - parsed).total_seconds()) < 60  # UTC-семантика

    async def test_bundle_writes_phase0_events(self, db):
        tg = "802"
        await _add_profile(db, tg)
        await _bundle(db, tg)
        cur = await db.execute("SELECT name FROM events WHERE tg_id=?", (tg,))
        names = {r["name"] for r in await cur.fetchall()}
        assert {"diet_program_created", "plan_created", "plan_saved"} <= names


# ── Transaction discipline (PATCH-5) ───────────────────────────────────────

class TestBundleAtomicity:
    async def test_failure_rolls_back_everything(self, db):
        tg = "900"
        await _add_profile(db, tg)
        bad_days = [  # второй день — не dict → SlotsError ВНУТРИ транзакции
            {"day": "Пн", "breakfast": "Каша"},
            "мусор вместо дня",
        ]
        with pytest.raises(SlotsError):
            await _bundle(db, tg, days=bad_days)
        # частичных записей не осталось: ни program, ни plan, ни meal_state, ни events
        for table in ("diet_programs", "weekly_plans", "meal_state", "events"):
            cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
            assert (await cur.fetchone())[0] == 0, table
        # после rollback соединение рабочее; день 0 = 4 фактических слота
        await _bundle(db, tg)
        assert len(await get_today_meals(db, tg)) == 4

    async def test_bundle_result_and_dates(self, db):
        tg = "901"
        await _add_profile(db, tg)
        result = await _bundle(db, tg, tz="Europe/Moscow")
        assert result["meal_states_created"] == 14  # 4+3+3+4
        assert result["end_date"] > result["start_date"]
