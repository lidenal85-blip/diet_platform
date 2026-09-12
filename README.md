# Diet Platform «Пухляш»

**Версия:** 1.0.0 (MVP)  
**Среда:** Linux (VPS), Python 3.10+  
**Статус:** 🟡 Production (MVP) — активные пользователи

Telegram-бот «Пухляш» — персональный ассистент по питанию, диетам и фитнесу с характером саркастичного рыжего кота.

## 🎯 Что делает

- **🍽️ Рецепты** — генерация рецептов через LLM с учётом предпочтений, аллергий, бюджета
- **📊 Диеты** — персонализированные планы питания на неделю с анализом КБЖУ
- **💪 Фитнес** — упражнения-разминки от ленивого кота (безопасно, без приседаний)
- **🛒 Список покупок** — автоформирование из выбранных рецептов
- **⏰ Напоминания** — о приёмах пищи с рецептами и упражнениями
- **🐱 Маскот** — Пухляш (саркастичный) и Ирисочка (эмпатичная, в разработке)

## 📂 Структура

```
diet_platform/
├── README.md               # этот файл
├── MANIFEST.md             # паспорт проекта
├── TEAM_NOTES.md           # операционный лог команды
├── PRODUCT_BACKLOG.md      # продуктовые требования (9 эпиков)
├── .env.example            # пример секретов
├── main.py                 # точка входа (FastAPI + aiogram)
├── bot.py                  # Telegram-бот «Пухляш»
├── database.py             # схема БД v1
├── database_migration_v2.sql  # миграция v2
├── diet_platform.db        # SQLite БД (WAL)
├── api/                    # FastAPI эндпоинты
├── bot_handlers/           # aiogram хендлеры
├── modules/                # бизнес-логика
│   ├── recipes/            # генерация рецептов
│   ├── fitness/            # фитнес-движок
│   ├── puhlyash/           # персона маскота
│   ├── irisochka/          # персона Ирисочки (план)
│   ├── notifier/           # уведомления (aiogram Bot)
│   ├── scheduler/          # APScheduler задачи
│   └── ...
├── workers/                # фоновые задачи
├── tests/                  # тесты
└── deploy/                 # systemd unit-файлы
```

## 🚀 Быстрый старт

```bash
cd projects/diet_platform/
cp .env.example .env
# Заполни TELEGRAM_BOT_TOKEN и GEMINI_API_KEYS в .env
pip install -r requirements.txt
python main.py
```

## 🔐 Безопасность

- Секреты только в `.env` (в .gitignore)
- Все LLM-вызовы через Leviathan LLMFactory (KeyPool + CircuitBreaker)
- SQLite WAL с `timeout=30` на все коннекты
- Нет raw `shell=True`, нет `os.system`

## 📄 Лицензия

MIT / Internal use.
