"""C-3.3 tests: экран «Мой план» (promts/12.md, §7).

Покрытие обязательных пунктов §7:
 1. активная программа + активная неделя → обзор через canonical chain;
 2. отсутствие активной программы → пустое состояние, без генерации;
 3. отсутствие недельного плана (программа без недель) → пустое состояние;
 4. корректность отображения: 7 дней, даты, 📍-сегодня, статусы, счётчик;
 5. переходы «Мой план» ↔ «Сегодня» (today:open → send_today_screen);
 6. архивные данные: archived-план/программа не показываются;
 7. callback дня — правильный plan_id + day_index; чужой plan_id — отказ;
 8. мусорный callback — без падений и изменений;
 9. событие plan_viewed при открытии (без чувствительных данных);
10. «🔄 Обновить» — перерисовка по свежим данным.

Тесты выполняются на temp-БД (monkeypatch DB_PATH) — прод-БД не используется
(соглашение test_today.py / test_planner_phase0).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest
import pytest_asyncio

import database
import planner
from bot_handlers import my_plan as mp
from bot_handlers import today as td  # go_today импортирует send_today_screen

pytestmark = pytest.mark.asyncio


# ── Fixture: temp DB via real init_db + patched DB_PATH (как в test_today) ──

async def _add_prod_columns(db_file: str) -> None:
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
    db_file = tmp_path / "my_plan_test.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    monkeypatch.setattr(mp, "DB_PATH", str(db_file))
    # переход «Мой план» → «Сегодня» уходит в модуль today со своей ссылкой
    # на DB_PATH — патчим и его (иначе go_today читает не ту БД в полном наборе)
    monkeypatch.setattr(td, "DB_PATH", str(db_file))
    await database.init_db()
    await _add_prod_columns(str(db_file))
    return db_file


async def _bundle(db_file, tg_id: str = "888") -> dict:
    """Активный план через штатный persist_plan_bundle (7 дней × 3 слота)."""
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


async def _overview(db_file: str, tg_id: str = "888"):
    async with aiosqlite.connect(str(db_file)) as conn:
        conn.row_factory = aiosqlite.Row
        return await planner.get_week_overview(conn, tg_id)


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


# ── 1. Активная программа + неделя → обзор по canonical chain ───────────────

async def test_overview_via_canonical_chain(db):
    bundle = await _bundle(db)
    ov = await _overview(db)
    assert ov is not None
    assert ov["plan_id"] == bundle["plan_id"]
    assert len(ov["days"]) == 7
    # 7 дней × 3 слота = 21 приём, все planned, порядок слотов сохранён
    total = sum(len(d["meals"]) for d in ov["days"])
    assert total == 21
    for day in ov["days"]:
        slots = [m["meal_slot"] for m in day["meals"]]
        assert slots == ["breakfast", "lunch", "dinner"]
        for m in day["meals"]:
            assert m["status"] == "planned"
            assert m["planned_text"]
            assert m["meal_state_id"]


# ── 2. Нет активной программы → пустое состояние без генерации ──────────────

async def test_no_program_empty_state_no_generation(db):
    msg = _make_message(uid=777)  # пользователь без программы/плана
    await mp.cmd_my_plan(msg)
    text = msg.answer.await_args.args[0]
    assert "Активной программы пока нет" in text
    kb = msg.answer.await_args.kwargs["reply_markup"]
    assert not hasattr(kb, "inline_keyboard")  # reply-меню, без inline-действий
    # пустой экран — это событие plan_viewed НЕ пишет (только просмотр плана)
    assert await _fetch_all(db, "SELECT name FROM events WHERE name='plan_viewed'") == []
    # никакой генерации
    for table in ("diet_programs", "weekly_plans", "meal_state"):
        rows = await _fetch_all(db, f"SELECT COUNT(*) AS n FROM {table}")
        assert rows[0]["n"] == 0, table


# ── 3. Программа без недельного плана → пустое состояние ────────────────────

async def test_program_without_week_empty_state(db):
    async with aiosqlite.connect(str(db)) as conn:
        conn.row_factory = aiosqlite.Row  # planner-функции ожидают Row (dict(row))
        await planner.create_program(
            conn, tg_id="555", diet_name="Сиропная", source="llm",
        )
        await conn.commit()
    msg = _make_message(uid=555)
    await mp.cmd_my_plan(msg)
    text = msg.answer.await_args.args[0]
    assert "Активной программы пока нет" in text
    weeks = await _fetch_all(db, "SELECT COUNT(*) AS n FROM weekly_plans")
    assert weeks[0]["n"] == 0  # неделя не была создана, экран не генерирует


# ── 4. Отображение: заголовок, 7 дней, даты, 📍, статусы, счётчик ────────────

async def test_screen_renders_week_correctly(db):
    await _bundle(db)
    msg = _make_message()
    await mp.cmd_my_plan(msg)
    text = msg.answer.await_args.args[0]
    assert "Мой план" in text
    assert "Средиземноморская" in text  # название программы в заголовке
    assert "Съедено за неделю: 0 из 21" in text
    # день «сегодня» помечен 📍, его дата соответствует actual start_date
    ov = await _overview(db)
    today_days = [d for d in ov["days"] if d["is_today"]]
    assert len(today_days) == 1
    td_iso = today_days[0]["date"]
    dmy = f"{td_iso[8:10]}.{td_iso[5:7]}"
    assert f"📍" in text and dmy in text
    # блюда показаны
    assert "Овсянка" in text and "Салат" in text
    # кнопки дней: только дни с приёмами, callback mp:{plan_id}:{1..7}
    kb = msg.answer.await_args.kwargs["reply_markup"]
    day_rows = [r[0] for r in kb.inline_keyboard[:-1]]
    assert len(day_rows) == 7
    for i, btn in enumerate(day_rows):
        assert btn.callback_data == f"mp:{ov['plan_id']}:{i + 1}"
        assert len(btn.callback_data.encode()) <= 64
    # последний ряд: «Сегодня» + «Обновить»
    last = kb.inline_keyboard[-1]
    assert [b.callback_data for b in last] == ["today:open", "mp:refresh"]


async def test_screen_shows_status_badges(db):
    await _bundle(db)
    # отметим 2 приёма в первый день напрямую через planner (writer)
    async with aiosqlite.connect(str(db)) as conn:
        conn.row_factory = aiosqlite.Row
        ov = await planner.get_week_overview(conn, "888")
        day0 = ov["days"][0]
        await planner.set_meal_status(conn, ov["plan_id"], "888", day0["date"],
                                      "breakfast", "eaten")
        await planner.set_meal_status(conn, ov["plan_id"], "888", day0["date"],
                                      "lunch", "skipped")
        await conn.commit()
    msg = _make_message()
    await mp.cmd_my_plan(msg)
    text = msg.answer.await_args.args[0]
    assert "Съедено за неделю: 1 из 21" in text
    # бейджи статусов в строке дня
    assert "🌅 Завтрак ✅" in text
    assert "🍽 Обед ⏭" in text


# ── 5. Переход «Мой план» → «Сегодня» (today:open) ──────────────────────────

async def test_go_today_transition(db):
    await _bundle(db)
    # my_plan сначала сам открыт (обзор есть)
    msg = _make_message()
    await mp.cmd_my_plan(msg)
    assert "Мой план" in msg.answer.await_args.args[0]
    # переход по today:open → экран «Сегодня» (не «пустое состояние»)
    call = _make_callback(888, "today:open")
    await mp.go_today(call)
    sent = call.message.answer.await_args
    assert "Что у нас на сегодня" in sent.args[0]
    # план реально прочитан: экран дня = 3 приёма × 3 ряда (заголовок + 2 действия) + «Обновить»
    assert len(sent.kwargs["reply_markup"].inline_keyboard) == 3 * 3 + 1


# ── 6. Архивные данные не показываются ──────────────────────────────────────

async def test_archived_plan_not_shown(db):
    bundle = await _bundle(db)
    old_plan_id = bundle["plan_id"]
    # архивируем активную неделю (штатный writer planner)
    async with aiosqlite.connect(str(db)) as conn:
        await planner.archive_plan(conn, old_plan_id, "888")
        await conn.commit()
    ov = await _overview(db)
    assert ov is None  # активной недели больше нет
    msg = _make_message()
    await mp.cmd_my_plan(msg)
    assert "Активной программы пока нет" in msg.answer.await_args.args[0]
    # archived-план не даёт действий: план не воссоздан,meal_state не тронут
    rows = await _fetch_all(
        db, "SELECT status FROM weekly_plans WHERE id=?", (old_plan_id,)
    )
    assert rows[0]["status"] == "archived"


# ── 7. Кнопка дня: правильные данные своим, чужой plan_id — отказ ───────────

async def test_day_button_own_and_foreign(db):
    await _bundle(db)
    ov = await _overview(db)
    day0 = ov["days"][0]
    # свой план: инфо-алерт с блюдами
    call = _make_callback(888, f"mp:{ov['plan_id']}:1")
    await mp.day_info(call)
    alert = _answer_text(call)
    assert "Завтрак" in alert and "Овсянка" in alert
    assert "запланировано" in alert
    # чужой пользователь без активной программы: план_id чужой недели не выдаёт
    # данных — canonical chain для него пуста, отказ «Активный план не найден»
    call_f = _make_callback(999, f"mp:{ov['plan_id']}:1")
    await mp.day_info(call_f)
    assert "не найден" in _answer_text(call_f)
    # устаревший plan_id (владелец тот же, id чужой) — отказ
    call_o = _make_callback(888, f"mp:00000000-0000-0000-0000-000000000000:1")
    await mp.day_info(call_o)
    assert "Неактуальная" in _answer_text(call_o)
    # никакие записи не изменились
    rows = await _fetch_all(db, "SELECT status FROM meal_state")
    assert all(r["status"] == "planned" for r in rows)


async def test_day_button_includes_status_word(db):
    await _bundle(db)
    async with aiosqlite.connect(str(db)) as conn:
        conn.row_factory = aiosqlite.Row
        ov = await planner.get_week_overview(conn, "888")
        day0 = ov["days"][0]
        await planner.set_meal_status(conn, ov["plan_id"], "888", day0["date"],
                                      "breakfast", "eaten")
        await conn.commit()
    call = _make_callback(888, f"mp:{ov['plan_id']}:1")
    await mp.day_info(call)
    alert = _answer_text(call)
    assert "отмечено" in alert  # eaten-слот помечен как отмечённый


# ── 8. Мусорный callback — без падений и изменений ──────────────────────────

async def test_bad_callbacks_safe(db):
    await _bundle(db)
    for bad in ("mp:", "mp:abc", "mp:abc:0", "mp:abc:8", "mp:abc:x", "mp:abc:1:extra",
                "mp::1", "nonsense"):
        call = _make_callback(888, bad)
        await mp.day_info(call)
        await mp.my_plan_refresh(call)
        # ни одного падения
    rows = await _fetch_all(db, "SELECT status FROM meal_state")
    assert all(r["status"] == "planned" for r in rows)


# ── 9. Событие plan_viewed при открытии (минимальный props) ─────────────────

async def test_plan_viewed_event_on_open(db):
    await _bundle(db)
    msg = _make_message()
    await mp.cmd_my_plan(msg)
    events = await _fetch_all(
        db, "SELECT name, props FROM events WHERE name='plan_viewed' AND tg_id='888'"
    )
    assert len(events) == 1
    props = json.loads(events[0]["props"])
    assert props == {"screen": "my_plan"}  # без текстов блюд и персональных данных


# ── 10. «🔄 Обновить» ────────────────────────────────────────────────────────

async def test_refresh_redraws_with_current_data(db):
    await _bundle(db)
    call = _make_callback(888, "mp:refresh")
    await mp.my_plan_refresh(call)
    args = call.message.edit_text.await_args
    assert "Мой план" in args.args[0]
    assert args.kwargs["reply_markup"].inline_keyboard  # клавиатура перерисована

    # после отметки — обновление показывает новый счётчик
    async with aiosqlite.connect(str(db)) as conn:
        conn.row_factory = aiosqlite.Row
        ov = await planner.get_week_overview(conn, "888")
        day0 = ov["days"][0]
        await planner.set_meal_status(conn, ov["plan_id"], "888", day0["date"],
                                      "breakfast", "eaten")
        await conn.commit()
    call2 = _make_callback(888, "mp:refresh")
    await mp.my_plan_refresh(call2)
    assert "Съедено за неделю: 1 из 21" in call2.message.edit_text.await_args.args[0]


async def test_refresh_empty_shows_empty_screen(db):
    call = _make_callback(777, "mp:refresh")  # пользователь без плана
    await mp.my_plan_refresh(call)
    edited = call.message.edit_text.await_args
    assert "Активной программы пока нет" in edited.args[0]
    assert _answer_text(call) == ""  # тост без ошибки


# ── Доп.: команда /myplan и пустой from_user безопасны ──────────────────────

async def test_cmd_alias_and_guard(db):
    await _bundle(db)
    msg = _make_message()
    msg.text = "/myplan"
    await mp.cmd_my_plan(msg)
    assert "Мой план" in msg.answer.await_args.args[0]

    ghost = MagicMock()
    ghost.from_user = None
    ghost.answer = AsyncMock()
    await mp.cmd_my_plan(ghost)  # не должен бросить
    ghost.answer.assert_not_awaited()
