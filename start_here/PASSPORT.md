# 🥬 Паспорт проекта: Diet Platform «Пухляш»

## Основные данные

| Параметр | Значение |
|---|---|
| **Название** | Diet Platform «Пухляш» |
| **Сервер** | leviathanstory.ru |
| **Путь** | `/opt/diet_platform` |
| **API-порт** | `8150` |
| **Сервис** | `diet-platform.service` |
| **База данных** | `/opt/diet_platform/diet_platform.db` (SQLite, WAL) |
| **Gemini-модель** | `gemini-2.5-flash` через Leviathan LLMFactory |
| **Gemini KeyPool** | 14 ключей (ротация round-robin + CircuitBreaker) |
| **Telegram-бот** | `@puhlyash_bot` (token в `.env`) |
| **Leviathan Agent** | управляет Leviathan → `diet_*` tools; обратной зависимости нет |
| **Репо** | `github.com/lidenal85-blip/Leviathan_Agent` |

---

## Архитектура

```
[Telegram Bot «Пухляш»]
        ↓
[Delivery API  :8150]  ←── HTTP GET (agent: diet_list, diet_pending, diet_dlq)
        ↓
[Search Gateway]  →  Google/Bing → URL list
        ↓
[Web Scraper]  →  HTML → raw_text
        ↓
[Diet Extractor]  →  Leviathan LLMFactory (gemini-2.5-flash)
        ↓
[Diet Core Registry]  →  SQLite (diet_master)
        →  MedicalGuard (whitelist валидация)
        →  AuditLog
```

---

## Модули

| Модуль | Путь | Ответственность |
|---|---|---|
| `building_blocks` | `/building_blocks/` | Общие контракты, config, logger |
| `search_gateway` | `/modules/search_gateway/` | URL-поиск через Serp API |
| `web_scraper` | `/modules/web_scraper/` | HTTP-скачивание + SSRF-защита |
| `diet_extractor` | `/modules/diet_extractor/` | LLM-экстракция (gemini-2.5-flash) |
| `diet_registry` | `/modules/diet_registry/` | Домен: валидация, аудит, версионирование |
| `delivery_api` | `/modules/delivery_api/` | FastAPI read-only API |
| `bot` | `/bot.py` | aiogram3 Telegram-бот |
| `worker` | `/workers/pipeline_worker.py` | Outbox-воркер конвейера |

---

## Функциональные режимы (бот)

### Базовые (MVP v1 — реализовано)
- `🔍 Найти диету` — поиск диет по запросу
- `🥗 Мои диеты` — список верифицированных
- `⏳ Ожидают оценки` — очередь модерации
- `🚨 Ошибки (DLQ)` — Dead Letter Queue

### Рецепты (v2 — в разработке)
- `👨‍🍳 Рецепты` — умные рецепты с режимами (быстро/домашний/ресторанный/ПП)
- `🏠 Шеф на телефоне` — диалоговый режим, пошагово
- `📦 Холодильник` — рецепты из перечня продуктов
- `💰 По бюджету` — меню на сумму
- `🔖 Сезонный рынок` — сезонные рецепты

### Премиум (v3 — по подписке)
- `👤 Профиль` — FSM-профиль: здоровье, цель, цикл, локация
- `📊 Индивидуальная диета` — генерация под управляемые параметры
- `🛋️ Меню на неделю` — 7-дневное меню + список покупок
- `💬 Рассылки` — email/SMS/WhatsApp диета и меню

---

## Ключевые файлы

```
/opt/diet_platform/
├── start_here/              ← НАЧИНАЙ СЮДА
│   ├── PASSPORT.md          ← этот файл
│   ├── MASTER_PROMPT.md     ← системный промт для AI
│   └── logs/
│       ├── session_YYYYMMDD_NNN.md   ← сессионные логи
│       └── snapshot_BLOCK_NAME.md    ← снапшоты по завершению блока
├── building_blocks/         ← shared kernel
├── modules/                 ← бизнес-модули
├── workers/                 ← Outbox pipeline worker
├── bot.py                   ← Telegram бот
├── main.py                  ← bootstrap
├── database.py              ← schema + migrations
└── .env                     ← секреты (NE в git)
```

---

## API эндпоинты (delivery_api)

| Метод | Путь | Описание |
|---|---|---|
| GET | `/health` | Здоровье |
| POST | `/api/v1/search` | Запустить поиск |
| GET | `/api/v1/sessions/{id}` | Статус сессии |
| GET | `/api/v1/diets` | Список диет |
| GET | `/api/v1/diets/{id}` | Деталь диеты |
| POST | `/api/v1/diets/{id}/verify` | Одобрить/отклонить |
| GET | `/api/v1/pending` | Очередь модерации |
| GET | `/api/v1/dlq` | Dead Letter Queue |

---

## Текущий роадмэп

- [x] v1: MVP pipeline (search → scrape → extract → registry → delivery)
- [x] v1: Telegram бот + постоянная клавиатура
- [x] v1: Подключение к Leviathan LLMFactory (gemini-2.5-flash)
- [x] v1: Leviathan Agent инструменты (`diet_*` tools)
- [x] v1: start_here / система логирования
- [ ] v2: Рецепты с режимами
- [ ] v2: Холодильник / Бюджет / Сезон
- [ ] v2: Шеф на телефоне (пошаговый режим)
- [ ] v3: Профиль пользователя + FSM индивидуальной диеты
- [ ] v3: Меню на неделю + список покупок
- [ ] v3: Рассылки email/SMS