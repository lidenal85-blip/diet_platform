"""C-3.2 tests: экран «Сегодня» (promts-задача C-3.2, §6).

C-3.2.1 (2026-09-21): визуальная группировка — у каждого блюда свой блок
клавиатуры (заголовок приёма·блюда·статуса + его 2 ряда действий), нажатие
заголовка — инфо-алерт. Покрытие:
  — у каждого блюда собственные кнопки, callback содержит id этого блюда;
  — нажатие заголовка — инфо о своём блюде, чужой id — отказ.

Покрытие 13 обязательных пунктов §6:
 1. get_today_meals() отдаёт приёмы на экране;
 2. пустое состояние (нет плана/блюд) без генерации;
 3. формирование callback_data всех 4 действий;
 4. отметка eaten;
 5. отметка skipped;
 6. событие meal_status_changed при успехе;
 7. отсутствие события при неудаче;
 8. защита чужой записи;
 9. некорректный/устаревший callback_data — без падений и изменений;
10. повторное нажатие — без повторного изменения;
11. «Заменить» — без изменения БД;
12. «Рецепт» — без генерации;
13. отсутствие регрессий — полный набор запускается отдельно.

Тесты выполняются на temp-БД (monkeypatch DB_PATH) — прод-БД не используется
(§16 Production Safety, соглашение test_planner_phase0/test_events_wiring).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest
import pytest_asyncio

import database
import planner
from bot_handlers import today as td

pytestmark = pytest.mark.asyncio


# ── Fixture: temp DB via real init_db + patched DB_PATH copies ──────────────

async def _add_prod_columns(db_file: str) -> None:
    """Колонки прод-схемы, добавляемые runtime-ALTER'ами хендлеров."""
    async with aiosqlite.connect(str(db_file)) as conn:
        for col in ("cook_level TEXT", "budget_level TEXT", "max_cook_time INTEGER",
                    "active_diet_mode TEXT"):
            try:
                await conn.execute(f"ALTER TABLE user_profiles ADD COLUMN {col}")
            except Exception:
                pass
        # recipes/fridge_sessions существуют в проде исторически, но init_db()
        # их не создаёт (RECIPES_SCHEMA объявлен, но не исполняется) —
        # зеркалим фактическое состояние прод-БД (idempotent IF NOT EXISTS).
        await conn.executescript(database.RECIPES_SCHEMA)
        await conn.commit()


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    db_file = tmp_path / "today_test.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    monkeypatch.setattr(td, "DB_PATH", str(db_file))
    await database.init_db()
    await _add_prod_columns(str(db_file))
    return db_file


async def _bundle(db_file, tg_id: str = "888") -> dict:
    """Активный план через штатный persist_plan_bundle (7 дней × 3 слота).

    Фикстура возвращает ПУТЬ к temp-БД — соединение открываем здесь
    (соглашение test_events_wiring: helpers работают с файлом БД).
    """
    days = [
        {
            "day": f"День {i + 1}",
            "breakfast": "Овсянка",
            "lunch": "Курица с рисом",
            "dinner": "Салат",
        }
        for i in range(7)
    ]
    async with aiosqlite.connect(str(db_file)) as db:
        db.row_factory = aiosqlite.Row
        return await planner.persist_plan_bundle(
            db, tg_id=tg_id, diet_name="Средиземноморская", source="llm",
            card={"name": "Средиземноморская"}, constraints={"goal": "похудеть"},
            days=days, user_timezone="Europe/Moscow",
        )


async def _fetch_all(db_file: str, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
    async with aiosqlite.connect(str(db_file)) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(sql, params)
        return await cur.fetchall()


async def _today_meals(db_file: str, tg_id: str = "888") -> list[dict]:
    async with aiosqlite.connect(str(db_file)) as conn:
        conn.row_factory = aiosqlite.Row
        return await planner.get_today_meals(conn, tg_id)


def _make_message(uid: int = 888) -> MagicMock:
    msg = MagicMock()
    msg.from_user.id = uid
    msg.answer = AsyncMock(return_value=MagicMock())
    return msg


def _make_callback(uid: int, data: str) -> MagicMock:
    call = MagicMock()
    call.from_user.id = uid
    call.data = data
    call.answer = AsyncMock(return_value=MagicMock())
    call.message = MagicMock()
    call.message.answer = AsyncMock(return_value=MagicMock())
    call.message.edit_text = AsyncMock(return_value=MagicMock())
    return call


def _answer_text(call: MagicMock) -> str:
    args = call.answer.await_args
    return str(args.args[0]) if args and args.args else ""


# ── 1. Экран показывает приёмы через get_today_meals ────────────────────────

async def test_today_screen_lists_meals(db):
    await _bundle(db)
    msg = _make_message()
    await td.cmd_today(msg)
    text = msg.answer.await_args.args[0]
    for title in ("Завтрак", "Обед", "Ужин"):
        assert title in text
    for dish in ("Овсянка", "Курица с рисом", "Салат"):
        assert dish in text
    # C-3.2.1: на каждый приём 3 ряда (заголовок-блок + 2 ряда действий) + «Обновить»
    kb = msg.answer.await_args.kwargs["reply_markup"]
    assert len(kb.inline_keyboard) == 3 * 3 + 1
    # первый real-ридер цепочки пишет plan_viewed
    events = await _fetch_all(db, "SELECT name FROM events WHERE tg_id='888'")
    assert "plan_viewed" in {r["name"] for r in events}


# ── 2. Пустое состояние ─────────────────────────────────────────────────────

async def test_today_empty_state_no_generation(db):
    msg = _make_message(uid=777)  # пользователь без плана
    await td.cmd_today(msg)
    text = msg.answer.await_args.args[0]
    assert "Активного плана пока нет" in text
    kb = msg.answer.await_args.kwargs["reply_markup"]
    # reply-меню (главная клавиатура), никаких inline-действий
    assert not hasattr(kb, "inline_keyboard")
    assert td._empty_screen() in text or "Подобрать диету" in text
    # никакой генерации: программа/план/meal_state не создались
    for table in ("diet_programs", "weekly_plans", "meal_state"):
        rows = await _fetch_all(db, f"SELECT COUNT(*) AS n FROM {table}")
        assert rows[0]["n"] == 0, table


# ── 1/2. C-3.2.1: у каждого блюда свой блок кнопок с его id ─────────────────

async def test_each_meal_has_own_action_block(db):
    """Блок на приём: ряд-заголовок (today:meal:{id}) и сразу под ним его
    4 действия с callback_data этого блюда — привязка «кнопка → блюдо»
    визуально однозначна."""
    await _bundle(db)
    meals = await _today_meals(db)
    assert len(meals) >= 3
    msg = _make_message()
    await td.cmd_today(msg)
    rows = msg.answer.await_args.kwargs["reply_markup"].inline_keyboard
    for i, meal in enumerate(meals):
        header_row = rows[i * 3]
        assert len(header_row) == 1
        assert header_row[0].callback_data == f"today:meal:{meal['id']}"
        dish = (meal["planned_text"] or "").strip()
        assert dish and dish in header_row[0].text  # блюдо в заголовке блока
        action_row1, action_row2 = rows[i * 3 + 1], rows[i * 3 + 2]
        assert [b.callback_data for b in action_row1] == [
            f"ms:{meal['id']}:eat",
            f"ms:{meal['id']}:skip",
        ]
        assert [b.callback_data for b in action_row2] == [
            f"ms:{meal['id']}:replace",
            f"ms:{meal['id']}:recipe",
        ]
    # последний ряд — «Обновить»
    assert rows[-1][0].callback_data == "today:refresh"


async def test_meal_header_info_alert_and_guards(db):
    """Заголовок блока: инфо о своём блюде со статусом; чужой/мусорный id —
    безопасный отказ, без изменений."""
    await _bundle(db)
    meals = await _today_meals(db)
    call = _make_callback(888, f"today:meal:{meals[0]['id']}")
    await td.today_meal_info(call)
    alert = _answer_text(call)
    assert "Завтрак" in alert and "Овсянка" in alert
    assert "запланировано" in alert
    # чужая запись — отказ
    call_f = _make_callback(999, f"today:meal:{meals[1]['id']}")
    await td.today_meal_info(call_f)
    assert "не найдена" in _answer_text(call_f)
    # мусорный callback — без падений
    call_b = _make_callback(888, "today:meal:")
    await td.today_meal_info(call_b)
    assert "Неактуальная" in _answer_text(call_b)
    # никаких изменений и событий от заголовков
    rows = await _fetch_all(db, "SELECT status FROM meal_state")
    assert all(r["status"] == "planned" for r in rows)
    assert await _fetch_all(db, "SELECT name FROM events WHERE name='meal_status_changed'") == []


# ── 3. Callback-контракт ────────────────────────────────────────────────────

async def test_callback_data_format():
    kb = td.meal_kb("abc123")
    datas = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert datas == [
        "ms:abc123:eat", "ms:abc123:skip",
        "ms:abc123:replace", "ms:abc123:recipe",
    ]
    for d in datas:
        assert len(d.encode()) <= 64  # лимит Telegram callback_data


async def test_parse_ms_callback_safe():
    assert td._parse_ms_callback("ms:id1:eat") == ("id1", "eat")
    assert td._parse_ms_callback(None) is None
    assert td._parse_ms_callback("") is None
    assert td._parse_ms_callback("ms:") is None
    assert td._parse_ms_callback("ms:id1") is None
    assert td._parse_ms_callback("ms:id1:bogus") is None
    assert td._parse_ms_callback("diet:id1") is None


# ── 4/5/6. eaten / skipped + событие ────────────────────────────────────────

async def _press(db, action: str, uid: int = 888):
    meals = await _today_meals(db, str(uid))
    meal = meals[0]
    call = _make_callback(uid, f"ms:{meal['id']}:{action}")
    handler = {"eat": td.ms_eat, "skip": td.ms_skip}[action]
    await handler(call)
    return meal


async def test_eat_marks_and_logs_event(db):
    await _bundle(db)
    meal = await _press(db, "eat")
    meals = await _today_meals(db)
    row = next(m for m in meals if m["id"] == meal["id"])
    assert row["status"] == "eaten"
    assert row["status_changed_at"] is not None
    events = await _fetch_all(
        db, "SELECT name, props FROM events WHERE name='meal_status_changed'"
    )
    assert len(events) == 1
    props = __import__("json").loads(events[0]["props"])
    assert props["to_status"] == "eaten"
    assert props["meal_state_id"] == meal["id"]
    # ничего чувствительного/лишнего в props
    assert "health_notes" not in props and "planned_text" not in props


async def test_skip_marks_and_logs_event(db):
    await _bundle(db)
    meal = await _press(db, "skip")
    meals = await _today_meals(db)
    row = next(m for m in meals if m["id"] == meal["id"])
    assert row["status"] == "skipped"
    events = await _fetch_all(
        db, "SELECT props FROM events WHERE name='meal_status_changed'"
    )
    assert len(events) == 1
    props = __import__("json").loads(events[0]["props"])
    assert props["to_status"] == "skipped"


# ── 7. Нет события при неудаче ──────────────────────────────────────────────

async def test_no_event_when_set_fails(db, monkeypatch):
    await _bundle(db)

    async def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(planner, "set_meal_status", boom)
    meals = await _today_meals(db)
    call = _make_callback(888, f"ms:{meals[0]['id']}:eat")
    await td.ms_eat(call)  # не должен бросить
    assert "Не получилось" in _answer_text(call)
    events = await _fetch_all(db, "SELECT name FROM events WHERE name='meal_status_changed'")
    assert events == []


# ── 8. Чужая запись не изменяется ───────────────────────────────────────────

async def test_foreign_meal_not_modified(db):
    await _bundle(db, tg_id="111")
    meals = await _today_meals(db, "111")
    foreign_id = meals[0]["id"]
    # другой пользователь жмёт чужую кнопку
    call = _make_callback(999, f"ms:{foreign_id}:eat")
    await td.ms_eat(call)
    assert "не найдена" in _answer_text(call)
    rows = await _fetch_all(db, "SELECT status FROM meal_state WHERE id=?", (foreign_id,))
    assert rows[0]["status"] == "planned"
    events = await _fetch_all(db, "SELECT name FROM events WHERE name='meal_status_changed'")
    assert events == []


# ── 9. Некорректный / устаревший callback_data ──────────────────────────────

async def test_bad_callback_data_safe(db):
    await _bundle(db)
    for bad in ("ms:", "ms:deadbeef:eat", "ms:whatever:junk", "ms:no-colons", "diet:123"):
        call = _make_callback(888, bad)
        await td.ms_eat(call)
        await td.ms_recipe(call)
        await td.ms_replace(call)
        # ни одного падения, ни одного изменения
    meals = await _today_meals(db)
    assert all(m["status"] == "planned" for m in meals)
    assert await _fetch_all(db, "SELECT name FROM events WHERE name='meal_status_changed'") == []
    # устаревший id (удалённая запись) — не падает и не пишет
    call = _make_callback(888, "ms:00000000-0000-0000-0000-000000000000:eat")
    await td.ms_eat(call)
    assert "не найдена" in _answer_text(call)


# ── 10. Повторное нажатие ───────────────────────────────────────────────────

async def test_repeat_press_is_noop(db):
    await _bundle(db)
    meal = await _press(db, "eat")
    first = await _fetch_all(db, "SELECT status, status_changed_at FROM meal_state WHERE id=?", (meal["id"],))
    call = _make_callback(888, f"ms:{meal['id']}:eat")
    await td.ms_eat(call)
    assert "Уже отмечено" in _answer_text(call)
    second = await _fetch_all(db, "SELECT status, status_changed_at FROM meal_state WHERE id=?", (meal["id"],))
    assert first[0]["status"] == second[0]["status"] == "eaten"
    assert first[0]["status_changed_at"] == second[0]["status_changed_at"]
    events = await _fetch_all(db, "SELECT name FROM events WHERE name='meal_status_changed'")
    assert len(events) == 1  # событие не задублировалось


async def test_status_change_after_final_is_blocked(db):
    """eaten → skip повторно не проводится (вне переходов C-3.2), без события."""
    await _bundle(db)
    meal = await _press(db, "eat")
    call = _make_callback(888, f"ms:{meal['id']}:skip")
    await td.ms_skip(call)
    assert "уже изменён" in _answer_text(call).lower() or "обнови" in _answer_text(call).lower()
    rows = await _fetch_all(db, "SELECT status FROM meal_state WHERE id=?", (meal["id"],))
    assert rows[0]["status"] == "eaten"
    events = await _fetch_all(db, "SELECT name FROM events WHERE name='meal_status_changed'")
    assert len(events) == 1


# ── 11. «Заменить» — без изменения БД ───────────────────────────────────────

async def test_replace_is_stub(db):
    await _bundle(db)
    meals = await _today_meals(db)
    call = _make_callback(888, f"ms:{meals[0]['id']}:replace")
    await td.ms_replace(call)
    assert "позже" in _answer_text(call).lower()
    rows = await _fetch_all(db, "SELECT status, replace_to FROM meal_state")
    assert all(r["status"] == "planned" and r["replace_to"] is None for r in rows)
    # _bundle пишет свои события (plan_created и т.п.) — заменa не должна добавить ни одного нового
    assert await _fetch_all(
        db, "SELECT name FROM events WHERE name='meal_status_changed'"
    ) == []


# ── 12. «Рецепт» — без генерации ────────────────────────────────────────────

async def test_recipe_stub_without_recipe_id(db):
    await _bundle(db)
    meals = await _today_meals(db)
    call = _make_callback(888, f"ms:{meals[0]['id']}:recipe")
    await td.ms_recipe(call)
    assert "не подключён" in _answer_text(call)
    # ничего не сгенерировано и не записано
    recipes = await _fetch_all(db, "SELECT COUNT(*) AS n FROM recipes")
    assert recipes[0]["n"] == 0
    assert await _fetch_all(db, "SELECT name FROM events WHERE name='meal_status_changed'") == []


async def test_recipe_shows_existing_saved_recipe(db):
    """Если рецепт уже привязан (recipe_id) — показывается сохранённый,
    без генерации нового (контроль повторного использования)."""
    await _bundle(db)
    meals = await _today_meals(db)
    async with aiosqlite.connect(str(db)) as conn:
        await conn.execute(
            "INSERT INTO recipes (id, title, mode, description, ingredients, steps, source) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                "rec-1", "Овсянка по-домашнему", "home", "Просто и быстро.",
                '["овсянка", "молоко"]', '["Свари.", "Съешь."]', "plan_link",
            ),
        )
        # привязываем рецепт к первому приёму — иначе хендлер честно скажет «не подключён»
        await conn.execute(
            "UPDATE meal_state SET recipe_id='rec-1' WHERE id=?", (meals[0]["id"],)
        )
        await conn.commit()
    call = _make_callback(888, f"ms:{meals[0]['id']}:recipe")
    await td.ms_recipe(call)
    # показ сохранённого: заголовок и контент из recipes, не «заглушка»
    sent = call.message.answer.await_args.args[0]
    assert "Овсянка по-домашнему" in sent and "Свари." in sent
    # новая генерация не запускалась — в таблице всё ещё одна запись
    recipes = await _fetch_all(db, "SELECT COUNT(*) AS n FROM recipes")
    assert recipes[0]["n"] == 1


# ── 13. Обновление экрана (refresh) ─────────────────────────────────────────

async def test_refresh_redraws(db):
    await _bundle(db)
    meal = await _press(db, "eat")
    call = _make_callback(888, "today:refresh")
    await td.today_refresh(call)
    args = call.message.edit_text.await_args
    text = args.args[0]
    assert "✅" in text  # отметка видна после обновления
    # C-3.2.1: заголовок блока съеденного блюда показывает статус ✅
    kb = args.kwargs["reply_markup"]
    headers = [
        r[0].text
        for r in kb.inline_keyboard
        if len(r) == 1 and r[0].callback_data.startswith("today:meal:")
    ]
    assert any("✅" in h for h in headers)
    assert meal["id"]  # экран построен по фактическим данным


async def test_refresh_without_plan(db):
    call = _make_callback(777, "today:refresh")
    await td.today_refresh(call)
    assert "План закончился" in _answer_text(call)
