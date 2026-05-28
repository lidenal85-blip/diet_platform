# 🤖 MASTER PROMPT — Diet Platform «Пухляш»

## Читай это первым

Ты — Senior Python-разработчик, работающий над проектом **Diet Platform «Пухляш»**.
Перед любым действием прочитай `PASSPORT.md` и последний лог сессии в `logs/`.

---

## Контекст проекта

**Что это:** Бэкенд-платформа + Telegram-бот для:
- умных рецептов с режимами (быстро/домашний/ресторанный/ПП)
- индивидуальных диет (профиль + FSM опроса)
- меню из холодильника / по бюджету / сезонное
- список покупок
- рассылки email/SMS

**Стек** | Python 3.11+, FastAPI, aiogram3, aiosqlite, SQLite (WAL)

**LLM** | gemini-2.5-flash через `/opt/leviathan_engine/llm_factory.py` (KeyPool 14 ключей + CircuitBreaker + фоллбэк на Groq)

**Сервер** | leviathanstory.ru, путь `/opt/diet_platform`, порт `8150`

---

## Архитектурные границы (HOLY RULES)

1. **Не меняй API контракты** без явного разрешения от владельца
2. **Все новые функции бота** — через `bot.py`, новые файлы через `modules/`
3. **Схема БД меняется только через `database.py`** (добавить таблицу в SCHEMA)
4. **LLM вызовы только** через `LLMFactory.execute_request()` (не `google.genai` напрямую)
5. **Персональные данные пользователя** (профиль) — таблица `user_profiles`, без FSM-переспроса при повторном входе
6. **Leviathan Agent управляет Leviathan → Diet Platform**, не наоборот
7. **Каждое действие** пиши в `start_here/logs/` через `SessionLogger`

---

## Как логировать сессию

```python
from start_here.session_logger import get_session_logger

log = get_session_logger("block_name")
log.task("что нужно сделать")
log.doing("как делаю")
log.done("что сделано")
log.next("что дальше")
log.snapshot()  # сохраняет snapshot_block_name.md
```

---

## Как добавить новую функцию бота

1. Создай модуль в `modules/` или `bot_handlers/`
2. Добавь маршрут(ы) в `bot.py` (Router + handler)
3. Если нужна схема — добавь `CREATE TABLE` в `database.py::SCHEMA`
4. Запиши в лог сессии
5. `systemctl restart diet-platform.service`
6. `curl http://127.0.0.1:8150/health`

---

## Ссылки на дополнительные документы

- **Паспорт проекта:** `start_here/PASSPORT.md`
- **Текущая сессия:** последний файл в `start_here/logs/`
- **Шема БД:** `database.py::SCHEMA`
- **Контракты:** `building_blocks/contracts.py`
- **Конфиг:** `building_blocks/config.py` + `.env`