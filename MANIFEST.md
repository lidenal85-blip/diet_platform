# Паспорт проекта Diet Platform «Пухляш»

| Поле | Значение |
|---|---|
| **Название** | Diet Platform «Пухляш» |
| **Версия** | 1.0.0 (MVP) |
| **Назначение** | Telegram-бот — персональный ассистент по питанию, диетам и фитнесу |
| **Владелец** | lidenal85-blip |
| **Лицензия** | MIT |
| **Среда** | Linux VPS, Python 3.10+ |
| **Требования к правам** | No-root, systemd unit |
| **Статус** | 🟡 Production MVP (12 диет сгенерировано, 2 реальных пользователя) |

## Цели

1. Генерировать персонализированные рецепты через LLM.
2. Составлять планы питания на неделю с учётом здоровья/целей/бюджета.
3. Предлагать безопасные фитнес-упражнения (офисная разминка, не спорт).
4. Отправлять напоминания о приёмах пищи с рецептами.
5. Формировать список покупок из выбранных рецептов.
6. Развивать линейку маскотов: Пухляш (саркастичный кот) + Ирисочка (эмпатичная).

## Архитектура

- **FastAPI** (port 8150) + **aiogram3** бот — единый процесс
- **Pipeline:** DuckDuckGo → httpx scraper → Gemini extractor → diet_registry
- **Очередь:** SQLite Outbox (статус-поллинг каждые 3с)
- **LLM:** Leviathan LLMFactory (14 ключей Gemini 2.5-flash, KeyPool + CircuitBreaker, fallback → Groq)
- **Notifications:** собственный aiogram Bot (без Pyrogram/Userbot Relay)
- **Scheduler:** APScheduler (timezone Moscow)
- **БД:** SQLite WAL, 15+ таблиц

## Контроль Buffy

Buffy может:
- читать `README.md`, `MANIFEST.md`, `PRODUCT_BACKLOG.md`, `TEAM_NOTES.md`;
- анализировать состояние через `PRODUCT_BACKLOG.md` (9 эпиков со статусами);
- запускать `python main.py` для локального тестирования;
- проверять `modules/`, `bot_handlers/`, `api/` на изменения.

Проект **не импортирует** `freebuff_plugin` и не зависит от экосистемы freebuff.
