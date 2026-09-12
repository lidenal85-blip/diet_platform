#!/usr/bin/env python3
"""E2E harness: полный флоу «Подбор диеты» через реального бота (без реального Telegram).

Что реально, а что нет:
  ✅ реальный aiogram Dispatcher (те же 8 роутеров, тот же порядок, что в bot.start_bot())
  ✅ реальная FSM-машина, реальные хендлеры, реальная SQLite (временная копия прод-БД)
  ✅ реальные LLM-вызовы (LLMFactory → KeyPool → Gemini/Groq)
  ⛔ исходящий транспорт Telegram перехвачен на уровне bot.session (FakeSession) —
     ни одно сообщение не уходит реальным пользователям.

Запуск (на сервере, где есть /opt/leviathan_engine, прод-БД и пул ключей):
    cd /opt/diet_platform && .venv/bin/python tests/e2e_diet_picker.py

Флаги:
    --fast       эвристики вместо LLM (проверяет механику FSM без расхода API-лимитов)
    --keep-db    не удалять временную копию БД после прогона (для отладки)
    --user-id N  id синтетического пользователя (по умолчанию 900000001)

Exit code: 0 = все шаги флоу прошли, 1 = провал (подробности в stdout).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from types import SimpleNamespace
from typing import Any

PROJECT = "/opt/diet_platform"

# ── Порядок имеет значение: env до импортов проекта ──────────────────────────
# config.py читает env_file=/opt/diet_platform/.env и/или process env.
# Все значения ниже переопределяют .env, поэтому реальный бот-токен не используется.
TEST_USER_ID = 900000001  # по умолчанию; меняется флагом --user-id


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="E2E diet-picker flow test")
    p.add_argument("--fast", action="store_true",
                   help="эвристики вместо LLM (без реальных Gemini-вызовов)")
    p.add_argument("--keep-db", action="store_true",
                   help="не удалять временную копию БД после прогона")
    p.add_argument("--user-id", type=int, default=TEST_USER_ID,
                   help="id синтетического пользователя")
    return p.parse_args()


ARGS = _parse_args()
TEST_USER_ID = ARGS.user_id

os.environ["DATABASE_PATH"] = tempfile.mkdtemp(prefix="dp_e2e_") + "/e2e.db"
os.environ["TELEGRAM_BOT_TOKEN"] = "0:E2E_FAKE_TOKEN"
os.environ["GEMINI_API_KEY"] = "E2E_SKIP"
os.environ["GEMINI_KEYS"] = "E2E_SKIP"

# PROJECT на пути ДО импортов проекта (tests/ не пакет приложения)
for p in (PROJECT, PROJECT + "/tests"):
    if p not in sys.path:
        sys.path.insert(0, p)

# ── Копия прод-БД через sqlite3 backup API (безопасно при живом сервисе) ──────

PROD_DB = "/opt/diet_platform/diet_platform.db"


def _copy_prod_db(tmp_db: str) -> None:
    """Онлайн-копия прод-БД (backup API, WAL-safe) + изоляция от реальных пользователей."""
    global TEST_USER_ID
    if not os.path.exists(PROD_DB):
        print(f"⚠️  Прод-БД не найдена: {PROD_DB} — создаём пустую (схему поднимут модули)")
    src = sqlite3.connect(PROD_DB)
    dst = sqlite3.connect(tmp_db)
    with dst:
        src.backup(dst)
    src.close()
    # Изоляция: синтетический пользователь не должен пересекаться с прод-данными.
    # Если id попал в прод случайно — сдвигаем на +1_000_000.
    has_profiles = dst.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='user_profiles'"
    ).fetchone()[0]
    if has_profiles and dst.execute(
        "SELECT COUNT(*) FROM user_profiles WHERE tg_id=?", (str(TEST_USER_ID),)
    ).fetchone()[0]:
        TEST_USER_ID += 1_000_000
        print(f"⚠️  tg_id={ARGS.user_id} существует в прод-БД → используем {TEST_USER_ID}")
    dst.close()


_copy_prod_db(os.environ["DATABASE_PATH"])

# ── Импорты проекта (только после env + DB-копии) ─────────────────────────────

import database  # noqa: E402
assert database.DB_PATH == os.environ["DATABASE_PATH"], (
    f"DB isolation broken: {database.DB_PATH}"
)

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.methods import TelegramMethod  # noqa: E402
from aiogram.types import Update, Message, Chat, User  #_entities  # noqa: E402

import bot  # noqa: E402

# ── Fake Telegram transport: всё, что бот «отправляет», падает в SENT ────────

SENT: list[dict[str, Any]] = []


class FakeSession(BaseSession):
    """Перехватчик исходящих вызовов: message.answer() идёт через bot.session."""

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        payload: dict[str, Any] = {
            "method": type(method).__name__,
            "chat_id": getattr(method, "chat_id", None),
            "text": getattr(method, "text", None),
            "reply_markup": getattr(method, "reply_markup", None),
        }
        SENT.append(payload)
        mid = 10_000 + len(SENT)
        return SimpleNamespace(
            message_id=mid,
            chat=SimpleNamespace(id=payload["chat_id"]),
            text=payload["text"],
            delete=lambda *a, **k: _ok(),
            edit_text=lambda *a, **k: _ok(),
        )

    async def stream_content(self, *a: Any, **k: Any):  # pragma: no cover
        yield b""
        return

    async def close(self) -> None:  # abstract in BaseSession
        return None


async def _ok() -> bool:
    return True


def make_update(text: str | None = None, callback_data: str | None = None) -> Update:
    """Синтетический Update от тестового пользователя."""
    chat = Chat(id=TEST_USER_ID, type="private")
    usr = User(id=TEST_USER_ID, is_bot=False, first_name="E2E", username="e2e_tester")
    if callback_data is not None:
        cq = SimpleNamespace(
            id=str(10_000 + len(SENT)),
            from_user=usr,
            chat_instance="e2e",
            data=callback_data.encode(),
            message=Message(
                message_id=5_000 + len(SENT),
                date=datetime.now(),
                chat=chat,
                from_user=usr,
            ),
        )
        return Update(update_id=len(SENT) + 1, callback_query=cq)
    msg = Message(
        message_id=5_000 + len(SENT),
        date=datetime.now(),
        chat=chat,
        from_user=usr,
        text=text,
    )
    return Update(update_id=len(SENT) + 1, message=msg)


async def feed(dp: Dispatcher, bot: Bot, update: Update) -> None:
    await dp.feed_update(bot, update)


def last_texts(n: int = 3) -> list[str]:
    return [s.get("text") or "" for s in SENT[-n:]]


def joined(n: int = 6) -> str:
    return "\n".join(last_texts(n))


# ── Шаги сценария ─────────────────────────────────────────────────────────────

STEP_RESULTS: list[tuple[str, bool, str]] = []


def step(name: str, ok: bool, detail: str = "") -> None:
    STEP_RESULTS.append((name, ok, detail))
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else ""))


async def run_flow(dp: Dispatcher, bot: Bot) -> bool:
    from bot_handlers.diet_picker import PickerStates

    print("▶ Шаг 1: /start")
    await feed(dp, bot, make_update(text="/start"))
    ok = "Пухляш" in joined(4)
    step("start приветствие", ok, "" if ok else joined(2)[:200])

    print("▶ Шаг 1b: 👤 Кабинет (регрессия R2 — мёртвая WebApp-ссылка)")
    await feed(dp, bot, make_update(text="👤 Кабинет"))
    t = joined(4)
    ok = ("Кабинет" in t) or ("Профиль не заполнен" in t)
    dead_link_gone = "Или открой в браузере" not in t and "leviathanstory" not in t
    step("кабинет отвечает", ok, "" if ok else t[:200])
    step("мёртвая WebApp-ссылка исчезла", dead_link_gone,
         "" if dead_link_gone else "в выводе осталась ссылка/кнопка кабинета")

    print("▶ Шаг 2: 🎯 Подобрать диету → Шаг 1 из 4")
    await feed(dp, bot, make_update(text="🎯 Подобрать диету"))
    t = joined(2)
    ok = "Шаг 1 из 4" in t and "Какая главная цель" in t
    step("опросник открыт", ok, "" if ok else t[:200])

    print("▶ Шаг 3: цель → возраст")
    await feed(dp, bot, make_update(text="🔥 Похудеть"))
    t = joined(2)
    ok = "Шаг 2 из 4" in t and "лет" in t
    step("цель принята", ok, "" if ok else t[:200])

    print("▶ Шаг 4: возраст → ограничения")
    await feed(dp, bot, make_update(text="30"))
    t = joined(2)
    ok = "Шаг 3 из 4" in t and "ограничения" in t.lower()
    step("возраст принят", ok, "" if ok else t[:200])

    print("▶ Шаг 5: ограничения → активность")
    await feed(dp, bot, make_update(text="Нет ограничений"))
    t = joined(2)
    ok = "Шаг 4 из 4" in t
    step("ограничения приняты", ok, "" if ok else t[:200])

    print("▶ Шаг 6: активность → подтверждение профиля")
    await feed(dp, bot, make_update(text="🚶 Умеренный"))
    t = joined(3)
    ok = "Твой профиль" in t and "Похудеть" in t
    step("профиль собран", ok, "" if ok else t[:300])

    print("▶ Шаг 7: 🚀 Подбирай! → 3 карточки (LLM или эвристика)")
    t0 = time.monotonic()
    await feed(dp, bot, make_update(text="🚀 Подбирай!"))
    dt = time.monotonic() - t0
    t = joined(8)
    ok = "Твои 3 варианта" in t and dt < 120
    step(f"3 карточки сгенерированы ({dt:.1f}s)", ok, "" if ok else t[:300])

    # Достаём имя первой диеты из карточек для следующего шага.
    # Кнопки живут в reply_markup, не в тексте; но карточки печатают "1. <Имя>".
    import re
    names = re.findall(r"<b>1\. (.+?)</b>", t)
    first_diet = names[0] if names else "Средиземноморская диета"

    print("▶ Шаг 8: выбор диеты → план на неделю")
    t0 = time.monotonic()
    await feed(dp, bot, make_update(text="1️⃣ " + first_diet))
    dt = time.monotonic() - t0
    t = joined(10)
    ok = (
        "Выбрана" in t
        and "План на неделю" in t
        and "Понедельник" in t
        and dt < 120
    )
    step(f"план на неделю получен ({dt:.1f}s)", ok, "" if ok else t[:300])

    # Финальные инварианты
    all_text = "\n".join(s.get("text") or "" for s in SENT)
    no_error = "❌ Ошибка" not in all_text
    step("нет ❌ Ошибка в исходящих", no_error,
         "" if no_error else all_text[all_text.find("❌ Ошибка"):][:200])
    return no_error and all(ok for _, ok, _ in STEP_RESULTS)


# ── main ──────────────────────────────────────────────────────────────────────

async def main() -> int:
    # LLMFactory может отсутствовать/падать без движка — --fast тогда единственный режим.
    if ARGS.fast:
        import bot_handlers.diet_picker as dp_mod
        dp_mod._LEV = False  # force heuristic path
        print("⚡ --fast: LLM отключён, используются эвристики")
    else:
        import bot_handlers.diet_picker as dp_mod
        if not dp_mod._LEV:
            print("⚠️  LLMFactory недоступен → авто-переход в --fast")
            ARGS.fast = True

    bot_ = Bot(token="0:E2E_FAKE_TOKEN")  # токен не используется — сессия фейковая
    bot_.session = FakeSession()
    dp = Dispatcher(storage=MemoryStorage())

    # Тот же состав и порядок роутеров, что в bot.start_bot()
    from bot_handlers.recipes import router as recipes_router
    from bot_handlers.schedule import router as schedule_router
    from bot_handlers.diet_picker import router as picker_router
    from bot_handlers.reactions import router as reactions_router
    from bot_handlers.meal_schedule_v2 import router as meal_v2_router
    from bot_handlers.cabinet import router as cabinet_router
    from bot_handlers.puhlyash_settings import router as puhlyash_router

    dp.include_router(reactions_router)  # callbacks: лайки, мастер
    dp.include_router(puhlyash_router)   # настройка Пухляша + тест
    dp.include_router(meal_v2_router)    # расписание v2
    dp.include_router(cabinet_router)    # FSM кабинета
    dp.include_router(picker_router)     # FSM подбора диеты
    dp.include_router(recipes_router)    # FSM рецептов
    dp.include_router(schedule_router)   # старый schedule (fallback)
    dp.include_router(bot.router)        # общие хендлеры

    print(f"▶ Прогон E2E (user_id={TEST_USER_ID}, fast={ARGS.fast})")
    t0 = time.monotonic()
    ok = await run_flow(dp, bot_)
    print(f"\n{'✅ E2E PASS' if ok else '❌ E2E FAIL'} за {time.monotonic() - t0:.1f}s "
          f"({len(SENT)} исходящих)")

    await bot_.session.close()
    if not ARGS.keep_db:
        db_dir = os.path.dirname(database.DB_PATH)
        shutil.rmtree(db_dir, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
