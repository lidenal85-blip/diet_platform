# ARCHITECTURE PHASE 0 — «Пухляш» / Product Foundation

> **Дата:** 2026-09-12 · **Составил:** Buffy / Freebuff (Stage 2.5, промт `promts/2_5.md`)
> **Источники:** PRODUCT_STRATEGY_2026-09.md, PRODUCT_RESEARCH_2026-09.md, APP_ANALYSIS_REPORT.md, PRODUCT_BACKLOG.md + **фактический код** (прочитан в этой сессии) и **фактическая БД** (read-only PRAGMA-инспекция whimco, 2026-09-12). При конфликтах: код+БД > документы; конфликты зафиксированы в §2.6 и §26.
> **Главное правило соблюдено:** ничего в проекте не изменено — один итоговый документ, read-only проверки только.
> **PATCH 2026-09-12 (Stage 3, `promts/3.md`):** внесены 10 архитектурных исправлений (календарные границы weekly_plans; каноническая цепочка «что есть сегодня»; обязательные DB-инварианты; семантика meal_state; транзакционная дисциплина LLM-вне-транзакции; allowlist профиля без health_notes; разделение tz-контракта Phase 0/1; уточнение ADR-4 по reminders; разделение событий Phase 0/Phase 1; инвариант ts(UTC) ↔ day_date(локальная)). Противоречащие старые формулировки удалены; Change Log — §29.
> **GATE 2026-09-12:** owner decisions зафиксированы владельцем (miniapp = DISABLE в Phase 0; timezone = `user_profiles.timezone`, default Europe/Moscow, не универсальная). Architecture Gate пройден: **GO** (§30).

---

## 1. Executive Summary

Phase 0 («продукт начинает помнить») технически реализуем **без destructive migration и без переписывания**: требуется 4 новые таблицы (`diet_programs`, `weekly_plans`, `meal_state`, `events`), один надстроечный модуль `planner`, шесть точечных EXTEND-правок существующих модулей и перевод Ирисочки на LLMFactory. Обнаружено два системных факта, которые стратегия Stage 2 недооценила: **(1) в проекте ноль foreign keys** (при `PRAGMA foreign_keys=ON` в схеме — целостность держится только на коде), **(2) существуют ДВЕ параллельные reminder-системы** (cron-broadcast в `meal_scheduler.py` и per-user jobs в `meal_schedule_v2.py`), которые в Phase 1 обе начнут претендовать на «напоминание по плану» — архитектурное решение зафиксировано сейчас (ADR-4: единственная система = meal_schedule_v2), консолидация кода — Phase 1. Блокеров к реализации нет; главный риск — не код, а **предметная двусмысленность timezone** (план на день требует определения «сегодня», которого в системе сейчас не существует).

**SAFE TO PROCEED: YES** — при соблюдении порядка из §20 и security-гейтов §15.

---

## 2. Current Architecture Forensics

### 2.1 Runtime (FACT)

```
systemd diet-platform.service (root, /opt/diet_platform, Restart=always)
 └─ main.py: asyncio.run(main())
     ├─ uvicorn.Server(modules.delivery_api.controllers.api:app)  :8150 (127.0.0.1)
     │    └─ lifespan: init_db() + asyncio.create_task(run_worker_loop())
     │         └─ workers/pipeline_worker: poll outbox каждые 3с (search→scrape→extract→registry)
     ├─ start_scheduler() + load_all_schedules()   ← APScheduler (AsyncIOScheduler, Europe/Moscow)
     │    ├─ cron-задачи breakfast/lunch/dinner (общие, из _get_active_users)
     │    └─ per-user cron-задачи из meal_schedule_v2._schedule_meal()
     └─ bot.start_bot(): aiogram3 Dispatcher, 8 роутеров, long-polling
```

### 2.2 Точки записи в БД (FACT)

| Модуль | Пишет в |
|---|---|
| bot_handlers/diet_picker.py | `user_profiles` (upsert goal/age/onboarding_done; `active_diet_mode='home'`) |
| bot_handlers/cabinet.py | `user_profiles` (cook/budget/excluded/time/recipe_day) |
| bot_handlers/puhlyash_settings.py | `user_profiles` (+runtime `ALTER TABLE ADD COLUMN` при первом запуске!) |
| bot_handlers/meal_schedule_v2.py | `meal_schedule` (CRUD приёмов) |
| bot_handlers/schedule.py (LEGACY) | `user_profiles.meal_*` + `notifications_enabled` |
| bot_handlers/recipes.py | `recipe_sessions`, `recipes`, `reactions` (через engine) |
| bot_handlers/reactions.py | `reactions` |
| api/miniapp_router.py, api/cabinet_router.py | `user_profiles` |
| modules/reactions/engine.py | `reactions` |
| workers/pipeline_worker + search/diet_registry | search_sessions, outbox, dlq, web_snapshots, diet_drafts, diet_master, audit_log |

### 2.3 Reminder-системы (FACT — их две)

1. **meal_scheduler.py** (запускается в main.py): `send_meal_notification(meal)` — для ВСЕХ активных юзеров, время из `user_profiles.meal_{breakfast,lunch,dinner}`, job-id `meal_{tg_id}`. Формирует рецепт Пухляша + упражнения, шлёт через `send_notification`. **О плане не знает.**
2. **meal_schedule_v2.py**: per-user cron-задачи, время из таблицы `meal_schedule`, job-id `meal_{tg_id}_{meal_name}`, повторное чтение enabled/notify при каждом срабатывании. Тоже генерирует рецепт на лету. **О плане не знает.**

**ASSUMPTION:** реально срабатывают обе (v2 переопределяет job-id `meal_{tg_id}_{meal_name}`, а scheduler — `meal_{tg_id}`; они не конфликтуют по id, и если у пользователя заполнены обе системы — он получает ДВЕ серии напоминаний). Решение зафиксировано в Phase 0 (ADR-4, PATCH-8): целевая единственная система — meal_schedule_v2; runtime-консолидация legacy scheduler — Phase 1 (§11). В Phase 0 обе системы продолжают работать как есть.

### 2.4 LLM flow (FACT)

Все генераторы → `LLMFactory.execute_request(prompt, system, model="gemini-3.1-flash-lite", driver="gemini", fallback=True, task_type="structured")`. KeyPool (3 Gemini + 6 Groq) + CircuitBreaker в `/opt/leviathan_engine`. **Исключение — Ирисочка** (§16). diet_picker имеет `_extract_json()` + эвристики; recipes/fitness имеют `json.loads` без защиты.

### 2.5 Тесты (FACT)

`tests/test_puhlyash.py` (persona, sync), `tests/test_vault_integration.py`, `tests/e2e_diet_picker.py` (E2E FSM-флоу, FakeSession, temp-копия БД, `--fast` эвристики). CI нет; на прод-сервере pytest не установлен.

### 2.6 Противоречия документация↔код (зафиксировано)

1. TEAM_NOTES: «Ирисочка не реализована» ↔ код: `modules/puhlyash/irisochka.py` существует и вызывается из recipes-flow.
2. MANIFEST: «14 ключей Gemini 2.5-flash» ↔ .env/KeyPool: 3 Gemini + 6 Groq (после миграции whimco).
3. Схема БД (`PRAGMA foreign_keys=ON`) ↔ факт: **ни одного FK в БД** — целостность обеспечивается кодом.
4. README: структура «modules/diet_registry/...» предполагает пакеты ↔ ISSUE-04: пакеты search_gateway/web_scraper/diet_extractor/diet_registry без `__init__.py` (импортируются как namespace-пакеты — работает, но хрупко).

---

## 3. Current DB Forensics

15 таблиц, **0 FK, 0 UNIQUE (кроме PK/content_sha256), 11 индексов**. Полная инспекция (whimco, read-only):

| TABLE | Purpose | Actual usage | Who writes | Who reads | Status | Problems |
|---|---|---|---|---|---|---|
| `user_profiles` | профиль | живая (2 записи, 41 колонка!) | picker/cabinet/puhlyash_settings/miniapp/schedule(legacy) | почти все | **CANONICAL** | 41 колонка = 4 слоя онбордингов; ALTER'ы в рантайме; `email/phone/track_cycle/cycle_*` — мёртвые поля (не читаются никем); `diary`, `saved_recipes`, `preferred_cuisines` — не используются |
| `meal_schedule` | приёмы v2 | живая (5 строк) | meal_schedule_v2 | meal_schedule_v2 | CANONICAL (для времени) | нет FK на tg_id; дублирует смысл user_profiles.meal_* |
| `user_profiles.meal_*` | время приёмов (v1) | полу-живая | schedule.py (legacy) + miniapp | meal_scheduler cron | **AMBIGUOUS** | второй источник времени; v1/v2 двойное обслуживание |
| `recipes` | рецепты | живая (61) | recipes-engine | recipes.py, scheduler | CANONICAL | **нет владельца** (user-agnostic) — реакция «save» указывает item_id, но рецепт не принадлежит юзеру |
| `reactions` | реакции | живая (1 строка!) | reactions.py, recipes.py | recipes.py | CANONICAL | item_id = строка без FK; реакция «на рецепт», не на planned meal |
| `recipe_sessions` | сессии генерации | technically-live (0 строк) | recipes.py | никто | AMBIGUOUS | пишется, никогда не читается |
| `shopping_lists` | списки покупок | мёртвая (0) | никто | никто | LEGACY | не связана с планом |
| `fridge_sessions` | холодильник | мёртвая (0) | никто | никто | LEGACY | `user_id` вместо `tg_id` — несогласованный нейминг |
| `diary_entries` | дневник | мёртвая (0) | никто | никто | LEGACY | — |
| `diet_master` | реестр найденных диет | живая (12, все pending_verification) | pipeline | /diets, verify | CANONICAL (контент) | **не связан с пользовательскими диетами** — два параллельных мира |
| `diet_drafts` | черновики экстракции | 0 строк | pipeline | pipeline | CANONICAL (инфра) | — |
| `search_sessions/outbox/dlq/web_snapshots/audit_log` | pipeline-инфра | живые (7/35/137/29/13) | pipeline | pipeline, /dlq | CANONICAL (инфра) | DLQ 137 записей не разбирается |
| `web_snapshots.content_sha256` | — | — | — | — | — | единственный UNIQUE-контракт в БД |

**Вывод:** паттерн проекта — «таблицы создаются, но жизнь в них не вдыхается» (4 мёртвых таблицы). Phase 0 обязан не повторить этот паттерн: каждая новая таблица = обязательный writer+reader в том же PR.

---

## 4. Canonical State Map

| Entity | Current source | Desired source (Phase 0+) | Exists? | Migration needed? |
|---|---|---|---|---|
| User | `user_profiles.tg_id` (строка) | то же | да | нет |
| Profile | `user_profiles` (4 слоя колонок) | `user_profiles` (**не переезжаем** — используем как есть) | да | нет (unified writer в §10) |
| Goal | `user_profiles.goal` | то же | да | нет |
| **Diet Program** | ❌ нигде (только текст на экране; `active_diet_mode='home'` — **legacy state shortcut**, не диета) | `diet_programs` (NEW) | нет | NEW + backfill (§19) |
| Weekly Plan | ❌ нигде (LLM-ответ в FSM-памяти) | `weekly_plans` (NEW, с календарными границами start_date/end_date в tz пользователя) | нет | NEW |
| Planned Meal | ❌ | `meal_state` (NEW) | нет | NEW |
| Recipe | `recipes` | `recipes` (+ nullable link из meal_state) | да | нет |
| Reaction | `reactions` (на recipe) | `reactions` (на recipe — остаётся) + **`meal_state.status` (на planned meal)** | да/нет | EXTEND semantics (ADR-4) |
| Deviation | ❌ (причина есть только в reactions.reason) | `meal_state.status + replace_to + note` | нет | NEW-поля, не отдельная таблица |
| Reminder | 2 системы (meal_scheduler cron + meal_schedule_v2 jobs) | meal_schedule_v2 (per-user) — **единственный writer**; meal_scheduler → deprecate в Phase 1 | да | CONSOLIDATE (ADR-4) |
| Character Context | `user_profiles.puhlyash_*` (5 колонок) + hardcode vibes | `user_profiles` + `character_memory` (Phase 3) | частично | нет в Phase 0 |
| Analytics Event | ❌ | `events` (NEW) | нет | NEW |

**Ключевое решение карты:** `active_diet_mode` — это **legacy state shortcut** (строка 'home'), а не активная диета. Он остаётся для fitness-DIET_HINTS (читается `fitness/engine.py`), но перестаёт быть «единственным следом выбора диеты». Источник истины об активной диете — `diet_programs.status='active'`.

---

## 5. Target Phase 0 Architecture

```
                       Telegram (aiogram3)
                              ↓
   ┌──────────────────────────┼──────────────────────────────┐
   │ bot_handlers             │                              │
   │  diet_picker ────────────┼──→ planner (NEW module)      │
   │  cabinet (unified FSМ)   │      │ creates              │
   │  meal_schedule_v2 ───────┼──→ weekly_plans ←────────────┤
   │  recipes (без изменений) │      │                       │
   └──────────────────────────┼───┼─────────────────────────┘
                              ↓   ↓
                    SQLite: diet_programs / weekly_plans / meal_state / events
                              ↑
   ┌──────────────────────────┼──────────────────────────────┐
   │ planner/context.py (NEW) │  profile → prompt context    │
   │ generators (EXTEND)      │  fitness/recipes/diet_picker │
   └──────────────────────────┴──────────────────────────────┘
```

Принцип: **новый модуль `planner`** (создание/чтение программ и планов) + точечные EXTEND-вызовы из существующих хендлеров. Существующие роутеры/FSM/генераторы не переписываются.

---

## 6. diet_program design (ADR-1)

**Ответ на вопрос промта «нужна ли отдельная сущность?» — ДА, отдельная таблица.** Обоснование: в существующих сущностях расширять нечего — `diet_master` — это **контентный реестр** (чужие диеты из интернета, верификация, sha-дедупликация; привязывать юзера к нему = ломать его смысл), `user_profiles` — профиль, а не домен. «Расширить» нечем — только создать.

```sql
-- НОВОЕ, без FK-ограничений (конвенция проекта: целостность в коде), но с индексами
CREATE TABLE IF NOT EXISTS diet_programs (
    id          TEXT PRIMARY KEY,              -- uuid4
    tg_id       TEXT NOT NULL,                 -- владелец (конвенция tg_id, строка)
    diet_name   TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'llm',   -- llm | heuristic | registry
    card        TEXT NOT NULL DEFAULT '{}',    -- JSON карточки (name/tagline/calories_range/
                                               --   duration_weeks/difficulty/pros/cons/key_foods)
    constraints_json TEXT NOT NULL DEFAULT '{}', -- снимок профиля на момент выбора (goal/age/restrictions)
                                                --   НЕ дублирует профиль — это «паспорт контекста» для адаптации
    status      TEXT NOT NULL DEFAULT 'active',-- active | paused | completed | replaced
    started_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_program_per_user
    ON diet_programs(tg_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_diet_programs_user ON diet_programs(tg_id, status);
```

- **Lifecycle:** `active → (paused → active) → completed | replaced`. Одновременно `active` — максимум одна на tg_id: **обязательный физический DB-инвариант** (не «recommended/optional»): `CREATE UNIQUE INDEX idx_one_active_program_per_user ON diet_programs(tg_id) WHERE status='active';` Кодовая проверка остаётся первой линией защиты, SQLite partial unique index — последней. Implementation precondition **выполнен 2026-09-12:** SQLite на whimco = 3.45.1, поддержка partial unique indexes проверена in-memory тестом (PARTIAL_UNIQUE_OK); перед деплоем — повторный прогон на копии прод-БД.
- **Ownership:** tg_id; чужую программу прочитать нельзя (все запросы WHERE tg_id=?).
- **Versioning:** НЕ нужен в Phase 0 (адаптация Phase 2 создаёт новую неделю, а не версию программы; «замена диеты» = новая строка со status='replaced' у старой). Future migration cost ≈ 0: добавление колонок аддитивно.
- **Пауза/завершение/новая:** методы `pause/complete/new` в `planner/programs.py`; новая программа при выборе другой диеты — старая помечается `replaced` (история сохраняется).
- **Связь с weekly_plan:** 1:N через `weekly_plans.program_id`.

## 7. weekly_plan design (ADR-2)

**Где план рождается сейчас (FACT):** `_get_week_plan()` в `diet_picker.py` возвращает dict `{days:[{day, breakfast, lunch, dinner, snack}], shopping_list, tips}` в памяти FSM → `_fmt_week_plan()` → текст → текст умирает. Формат LLM-ответа уже структурирован и латиница-ключи — **сохраняем текущий формат как storage-формат** (ADR-2: не менять промпт = не рисковать качеством).

```sql
CREATE TABLE IF NOT EXISTS weekly_plans (
    id          TEXT PRIMARY KEY,
    program_id  TEXT NOT NULL,                 -- → diet_programs.id (логическая FK, код-контроль)
    tg_id       TEXT NOT NULL,
    week_no     INTEGER NOT NULL DEFAULT 1,    -- 1..N внутри программы
    start_date  TEXT NOT NULL,                 -- 'YYYY-MM-DD' в tz пользователя: календарная дата ПЕРВОГО дня плана
    end_date    TEXT NOT NULL,                 -- 'YYYY-MM-DD' в tz пользователя: start_date + 6 дней
    days        TEXT NOT NULL,                 -- JSON: массив 7 дней В ТЕКУЩЕМ формате _get_week_plan
    shopping_list TEXT NOT NULL DEFAULT '[]',  -- JSON array
    tips        TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL DEFAULT 'active', -- active | archived
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_plan_per_program
    ON weekly_plans(program_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_weekly_plans_program ON weekly_plans(program_id, week_no);
CREATE INDEX IF NOT EXISTS idx_weekly_plans_user ON weekly_plans(tg_id, status);
```

- **Инвариант (физический, DB — обязателен):** одна `active` неделя на программу — `CREATE UNIQUE INDEX idx_one_active_plan_per_program ON weekly_plans(program_id) WHERE status='active';` (поддержка проверена: SQLite 3.45.1 на whimco, partial unique enforced). Прошлые недели хранятся как archived — это и есть данные для адаптации.
- **Календарная семантика (PATCH-1):** неделя владеет собственными границами `start_date`/`end_date` (ISO 'YYYY-MM-DD', **вычисляются в timezone пользователя**), инвариант `end_date = start_date + 6 дней`. Неделя НЕ восстанавливается косвенно через meal_state. Правило: `start_date` = «сегодня» в tz пользователя в момент генерации плана (план покрывает 7 дней, включая сегодня); календарная дата дня с индексом i = start_date + i.
- **Не нормализуем days по таблицам** (ADR-2: 7 дней × 4 приёма = JSON-блоб достаточно; нормализация нужна только когда meal_state начинает писать в дни).

### Planned Meal design (ADR-3)

**Каноническая цепочка ответа на вопрос «что пользователь должен был съесть сегодня?» (PATCH-2, архитектурный инвариант):**

```
user → active diet_program (diet_programs WHERE tg_id=? AND status='active')
     → active weekly_plan (weekly_plans WHERE program_id=? AND status='active')
     → meal_state WHERE plan_id=? AND day_date=today
```

Запрос `meal_state WHERE tg_id=? AND day_date=today` **сам по себе** однозначным источником НЕ является: он может вернуть строки архивной/заменённой программы. Однозначность даёт только проход по цепочке: сначала активная программа пользователя, затем активная неделя этой программы, и только затем meal_state этой недели на дату. Реализуется единственной функцией `planner.get_today_meals(tg_id, today)`.

```sql
CREATE TABLE IF NOT EXISTS meal_state (
    id          TEXT PRIMARY KEY,
    tg_id       TEXT NOT NULL,
    plan_id     TEXT NOT NULL,                 -- → weekly_plans.id
    day_date    TEXT NOT NULL,                 -- 'YYYY-MM-DD' В TIMEZONE ПОЛЬЗОВАТЕЛЯ (см. ADR-6)
    day_name    TEXT NOT NULL,                 -- 'Понедельник' (из LLM JSON, для отображения)
    meal_slot   TEXT NOT NULL,                 -- breakfast | lunch | dinner | snack
    planned_ref TEXT NOT NULL,                 -- JSON-указатель: {"day_index":0,"meal":"breakfast"}
    planned_text TEXT NOT NULL DEFAULT '',     -- денормализованное название для напоминаний/замены
    status      TEXT NOT NULL DEFAULT 'planned', -- planned|eaten|skipped|replaced|missed
    recipe_id   TEXT,                          -- nullable → recipes.id (если рецепт сгенерирован)
    replace_to  TEXT,                          -- JSON: что выбрал при replace
    note        TEXT,                          -- свободная причина (опционально, Phase 1)
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(plan_id, day_date, meal_slot)
);
CREATE INDEX IF NOT EXISTS idx_meal_state_user_day ON meal_state(tg_id, day_date);
```

- `planned_ref` (day_index+meal) — **однозначный адрес** planned meal внутри плана; `day_date` — календарная привязка (напоминание всегда знает дату); UNIQUE-контракт против дублей.
- **Семантика meal_state (PATCH-4):** `meal_state` = materialized state **только для фактически запланированных meal slots**. Записи НЕ создаются по шаблону «7×4=28»: если в конкретном дне плана присутствуют только breakfast/lunch/dinner — создаются ровно три записи этого дня; искусственный `snack` не создаётся (иначе система будет считать его пропущенным приёмом). Правило: один meal_state на каждый meal slot, реально присутствующий в JSON дня плана.
- **Транзакционная дисциплина (PATCH-5):** запрещена схема «BEGIN → LLM generation → DB writes → COMMIT». Единственно допустимая: `LLM generation → validation → BEGIN TRANSACTION → persist program/plan/meal_state/events → COMMIT`. LLM вызывается **до** транзакции; транзакция защищает только атомарность сохранения уже подготовленных данных — при ошибке LLM БД не находится внутри незавершённой длинной транзакции.
- **Reaction владеет meal_state, а не reactions:** `reactions` (лайк/дизлайк рецепта) остаётся как есть; факт «съел» — это статус planned meal, не реакция на рецепт (ADR-4). Разделение: `reactions` = «понравился ли рецепт», `meal_state.status` = «что произошло с приёмом».

## 9. Profile → Generator analysis

Метод: не названия полей, а фактическое чтение кода (`prompt_builder.py`, `fitness/engine.py`, `diet_picker.py`, `meal_scheduler.py`, persona.py прочитаны).

| Profile field | Stored | Read (где-то) | Passed to generator | Used in prompt | Used by deterministic logic |
|---|---|---|---|---|---|
| cook_level | ✅ | ✅ | recipes: **ДА** | ✅ COOK_LEVEL_HINTS | — |
| budget_level | ✅ | ✅ | recipes: **ДА** | ✅ BUDGET_HINTS | — |
| experiment_level | ✅ | ✅ | recipes: **ДА** | ✅ | — |
| max_cook_time | ✅ | ✅ | recipes: **ДА** | ✅ TIME_HINTS | — |
| excluded_foods | ✅ | ✅ | recipes: **ДА** | ✅ (строкой) | — |
| **goal** | ✅ | picker only | ❌ recipes/fitness | ❌ | только user_profiles-запись |
| **age** | ✅ | picker only | ❌ | ❌ | нет |
| **weight_kg / height_cm** | ✅ | ❌ НИКЕМ | ❌ | ❌ | нет |
| **health_notes** | ✅ | ❌ | ❌ | ❌ | нет |
| **restrictions (онбординг picker)** | ⚠️ теряется! | ❌ | ❌ | ❌ | нет |
| **location** | ✅ | ❌ | ❌ | ❌ | нет |
| activity (FSM picker) | ⚠️ в FSM-данных, в БД НЕ пишется | ❌ | ❌ | ❌ | нет |
| active_diet_mode | ✅ | fitness/scheduler | fitness (DIET_HINTS) | ✅ (косвенно) | да (hint) |
| cuisine_prefs / preferred_cuisines | ✅ | ❌ | ❌ | ❌ | нет |
| timezone | ❌ **нет колонки** | ❌ | ❌ | ❌ | Europe/Moscow hardcode |
| gender | ✅ | ❌ | ❌ | ❌ | нет |

**Критические находки:** (1) `restrictions` из опросника picker'а **вообще не сохраняется в БД** — FSM `update_data` держит его только в памяти диалога (проверено: `got_restrictions` делает `update_data`, в БД пишутся только goal/age) — т.е. даже «слабая персонализация» у picker-дiet нет; (2) `activity` тоже теряется; (3) timezone отсутствует физически.

**Минимальный реальный profile context (Phase 0) — PATCH-6: allowlist по генераторам, НЕ «профиль → все поля → всем». `health_notes` могут содержать чувствительную медицинскую информацию и **не передаются автоматически ни одному генератору**. Контекст разделён на явные области:

| Generator | Allowed fields (allowlist) |
|---|---|
| Diet planner (диета/план) | goal, age, activity, restrictions, допустимые пищевые ограничения |
| Recipe generator | restrictions, excluded_foods, cook_level, budget_level, max_cook_time |
| Fitness/exercise | activity, goal |

Если конкретному генератору когда-либо понадобятся health_notes — это отдельное архитектурное решение с явным контрактом (ADR), не расширение allowlist по умолчанию. Сопутствующие правила: health_notes не попадают в events; не попадают в debug/info-логи; полный profile context не логируется никогда.

`planner/context.py` реализует **отдельные сборщики**: `build_diet_context(tg_id)`, `build_recipe_context(tg_id)`, `build_fitness_context(tg_id)` — вместо одного универсального. **Добавить колонки:** `restrictions TEXT`, `activity TEXT`, `timezone TEXT DEFAULT 'Europe/Moscow'` (однократный аддитивный ALTER — конвенция проекта уже такая, puhlyash_settings так делает). Europe/Moscow — default для legacy/unknown пользователей, **не универсальная tz для всех** (см. ADR-6).

## 10. Unified Onboarding design

**FACT-карта двух онбордингов:**

| | diet_picker (🎯 Подобрать диету) | cabinet (👤 Кабинет) |
|---|---|---|
| Поля | goal, age, restrictions, activity | cook_level, experiment_level, budget_level, max_cook_time, excluded_foods, recipe_day_time |
| Пишет | goal/age/onboarding_done (restrictions/activity **теряются**) | все свои |
| Пересечения | нет | нет |
| Использование | при подборе диеты | при кабинет-доступе |
| Legacy | — | schedule.py (v1-расписание) — DEPRECATE |

**Проектируемый канонический флоу (не переписывая handlers — склейка):** `/start` → [если профиля нет] → ветка A = FSM diet_picker (goal→age→restrictions→activity) с **дописыванием** в БД после каждого шага (фикс потери: restrictions/activity пишутся сразу) → ветка B = FSM cabinet (cook→budget→…) → подтверждение → **сразу** `planner.create_program()` + `planner.create_first_plan()` → первый план показан и сохранён. Кнопка «Пропустить» для B; возвращение к B через кабинет. Переиспользуем: оба FSM-класса, клавиатуры, валидацию возраста — без переписывания; меняется только (а) сохранение restrictions/activity, (б) точка входа `/start`, (в) финальный шаг создаёт program+plan.

## 11. Reminder integration plan (ADR-4)

**Целевая связь (не реализуется сейчас):** `WeeklyPlan → meal_state(day_date=today, status=planned) → reminder читает meal_state → Reaction пишет в meal_state`.

**Решение по двум системам (PATCH-8, однозначная формулировка):** архитектурное решение принимается в Phase 0: **meal_schedule_v2 — целевая единственная reminder-система** (per-user, таблица, чистый enable/disable). Runtime-миграция/deprecation legacy-шедулера (`meal_scheduler.send_meal_notification`, cron-задачи) выполняется в **Phase 1**. В Phase 0 существующий scheduler **не ломается** ради архитектурного решения — он остаётся работать как есть; Phase 0 только фиксирует целевое состояние и создаёт данные, на которые Phase 1 переключит reminder-чтение.

Проверка «старого плана» (Phase 1): reminder читает meal_state **только через каноническую цепочку PATCH-2** (`planner.get_today_meals(tg_id, today)`), никогда прямым запросом `(tg_id, day_date=today)`; если активная программа/неделя отсутствуют или дата вне [start_date, end_date] — fallback на старое поведение (генерация рецепта). Двойная защита от неактуальности: `weekly_plans.status='active'` + календарные границы недели.

## 12. Reaction model

Существует: `reactions` (лайк/диз/save/альтернативы на рецепты, reason) — **сохраняем как есть**. Изменить позже (Phase 1): статусные кнопки в напоминании пишут в `meal_state.status` (planned→eaten/skipped/replaced; расширение enum — ТОЛЬКО по мере необходимости, начать с 3 значений + `missed` как системный). Reaction относится к **planned meal** (meal_state), а не к recipe; `reactions` продолжает обслуживать вкусы. Это принципиальный ответ промта: **две разные сущности, не смешивать.**

## 13. Adaptation prerequisites

**REQUIRED NOW** (без этого адаптация Phase 2 невозможна):
- meal_state с датами/статусами (что планировали/что произошло);
- сохранённые weekly_plans (архив недель);
- profile context реально доходит до генератора адаптации;
- reactions (уже есть);
- `constraints_json` в diet_programs (контекст выбора).

**LATER (не строить):** vector memory, behavior-aggregate-инфраструктура (aggregates можно посчитать SQL-запросом из meal_state в момент адаптации), world-events, дневник настроения/голода, веса.

## 14. Analytics model

Существующая система: отсутствует (FACT). Минимальный event model (сверен со стратегией §11 Stage 2, не принят автоматически):

**Phase 0 events (PATCH-9 — минимальный набор, без meal/reminder-цикла):**

| Event | Trigger | Required props | Source | Purpose | Metric |
|---|---|---|---|---|---|
| onboarding_started | /start без профиля | tg_id | bot | воронка входа | M1 |
| onboarding_completed | финальный шаг онбординга | tg_id, duration_s | bot | воронка входа | M1 |
| diet_program_created | planner.create_program | tg_id, source | planner | core сработал | M2 |
| plan_created | planner.create_plan | tg_id, program_id, week_no | planner | ядро | M2/M3 |
| plan_saved | программа+неделя сохранены в одной транзакции | tg_id, program_id, plan_id | planner | якорь M3/§27-цепочки | M3 |
| plan_viewed | показ карточек/плана | tg_id, program_id | bot | — | M3 |
| llm_call | LLMFactory execute | model, driver, latency_ms, ok | llm | диагностика/оценка стоимости | M12 (оценочно) |

**Phase 1 events (появляются только с замыканием meal/reminder-цикла; в Phase 0 НЕ заявляются):** reminder_sent, reminder_clicked, meal_reaction, meal_state_changed, eaten/skipped/replaced/missed. Event taxonomy не расширяется без необходимости.

Таблица `events(id, tg_id, name, props JSON, ts)` + хелпер `log_event()`; write-only (аналитика чтения — отдельный вопрос Phase 5). **Не логировать** персональный контент сообщений и health-данные (§15).

**Инвариант времени (PATCH-10):** `events.ts` — абсолютное время события, **UTC**; `meal_state.day_date` — **локальная календарная дата пользователя**. Никогда не использовать `events.ts` для определения того, к какому локальному дню относится приём пищи; никогда не вычислять «сегодня» из ts. Обе величины связаны только через tz профиля (planner-хелпер).

## 15. Security review

| Security Gate | Current state | Risk | Required before Phase 0 |
|---|---|---|---|
| Telegram identity (miniapp) | miniapp_router читает/пишет профиль по голому tg_id (FACT) | чтение/порча чужих профилей | **РЕШЕНО владельцем (2026-09-12): DISABLE всех незащищённых miniapp-роутов в Phase 0.** initData-валидация НЕ реализуется в Phase 0; повторное включение — только после отдельной задачи валидации |
| Bot API callbacks | aiogram подлинность апдейтов гарантирует | низкий | — |
| User data | email/phone в профиле существуют, но не заполняются | средний | не заполнять; в events — только tg_id+props без PII-контента |
| Health data | health_notes в профиле, пока не читается | средний | health_notes НЕ передаются генераторам (allowlist PATCH-6); если когда-либо понадобятся — отдельный ADR + дисклеймер «не мед. рекомендация» в output |
| LLM secrets | .env 600, KeyPool на сервере | низкий | без изменений |
| LLM logging | промпты не логируются целиком (FACT — только warnings) | низкий | сохранить статус-кво |
| **Irisochka raw urllib** | читает `/opt/leviathan_engine/agent_service/.env` напрямую, sync-вызовы в event loop | средний | перевод на LLMFactory (§16) |
| API :8150 | 127.0.0.1 (fixed R4) | низкий | без изменений |
| tg_id доверие в bot-флоу | все записи по message.from_user.id (серверная гарантия Telegram) | низкий | — |
| Логи | файл-лог без PII-контента | низкий | events не должны писать тексты сообщений |

## 16. Irisochka integration (минимальный Phase 0 scope)

**FACT:** `modules/puhlyash/irisochka.py` — мышка-нутрициолог; `comment_recipe()` вызывается из recipes-flow; `_gemini()` — **raw urllib, sync, чтение чужого .env, обход LLMFactory/KeyPool/CircuitBreaker** — единственный оставшийся обходной путь. **Canonical product fact (промт): Ирисочка = фитоняшка** — образ меняется в Phase 3 (Character Bible), Phase 0 **не трогает личность**, только технический путь.

**Минимальный scope Phase 0:** заменить тело `_gemini()` на вызов `LLMFactory.execute_request(..., model=gemini-3.1-flash-lite, fallback=True)` (~10 строк, сигнатура публичных функций не меняется); устаревший образ остаётся до Phase 3. Не превращать в character system. (Проверка: get_quick_tip fallback сохраняется.)

## 17. ADRs

**ADR-1 diet_program (NEW table).** Context: диета не персистентна; diet_master — контент-реестр чужих диет; user_profiles — не домен. Options: (a) расширить user_profiles колонками, (b) переиспользовать diet_master, (c) новая таблица. Chosen: (c). Why: чистый aggregate с lifecycle; (a) продолжает анти-паттерн «41 колонка», (b) смешивает контент и ownership. Trade-offs: ещё одна таблица в проекте с историей мёртвых таблиц — митигируется обязательным writer+reader в том же PR. Rejected: (a),(b). Migration cost: 0 (аддитивно).

**ADR-2 weekly_plan (NEW table, JSON-дни).** Context: план генерится в FSM и умирает; LLM-формат уже структурирован. Options: (a) нормализовать days/meals в таблицы, (b) JSON-блоб. Chosen: (b) — формат LLM сохраняется, риск качества генерации не трогаем; нормализация НЕ нужна пока meal_state не пишет в дни (когда понадобится — days останутся чтимыми, meal_state — адресуемым слоем). Trade-offs: SQL-запросы внутрь дня сложнее (json_extract — ок в SQLite). Rejected: (a) — преждевременная нормализация. Migration cost: низкая.

**ADR-3 planned_meal = meal_state (NEW table).** Context: нужен однозначный ответ «что должен был съесть сегодня». Chosen: отдельная `meal_state` с UNIQUE(plan_id, day_date, meal_slot), planned_ref + денормализованный planned_text. Why: адресуемость + статус-машина + дата в tz пользователя. Trade-offs: денормализация названий — принимаю (plan_id+ref позволяет восстановить). Migration cost: 0.

**ADR-4 reaction ownership + reminder consolidation (уточнён PATCH-8).** Context: reactions(рецепт) существуют; два reminder-потока. Chosen: статус приёма живёт в meal_state.status; reactions — только вкусы. Reminder: **архитектурное решение принимается в Phase 0 — meal_schedule_v2 = целевая единственная reminder-система; runtime-миграция legacy scheduler — Phase 1** (в Phase 0 ничего не отключается). Why: смешение статуса приёма и оценки рецепта создаст два смысла у одного поля; двойные напоминания — прямой юзер-фейс; но поломка текущих напоминаний в Phase 0 недопустима. Trade-offs: между Phase 0 и Phase 1 обе системы продолжают работать параллельно (известный долг, ограничен сроком до Phase 1). Rejected: «реакция = еда» в reactions; отключение scheduler в Phase 0. Migration cost: низкая.

**ADR-5 canonical profile (EXTEND user_profiles).** Context: 41 колонка из 4 онбордингов; 5 полей теряются. Chosen: НЕ переезжать в новую таблицу; +3 колонки (restrictions, activity, timezone), единый writer-контракт (§10), context-builder как единая точка чтения. Why: миграция профиля = риск при 2 живых пользователях и 0 выгоды. Trade-offs: таблица остаётся перегруженной — фиксируется документом, не кодом. Migration cost: 0.

**ADR-6 timezone (EXTEND; контракт разделён по фазам — PATCH-7).** Context: Europe/Moscow зашит; «сегодня» не определено. Chosen: колонка `timezone` (Europe/Moscow — default только для legacy/unknown пользователей, не универсальная tz). **Phase 0 — tz используется для календарной семантики:** `weekly_plans.start_date`, `weekly_plans.end_date`, `meal_state.day_date`, определение «сегодня» (zoneinfo, planner-хелпер). **Phase 1 — tz дополнительно используется для:** scheduler, reminders, локальное время уведомлений (перевод CronTrigger на per-user tz). Why: календарная семантика нужна сразу, шедулинг — только с замыканием петли. Trade-offs: до Phase 1 напоминания уходят по МСК независимо от tz профиля — осознанно. **Подтверждено владельцем 2026-09-12:** `user_profiles.timezone` — канонический tz; Europe/Moscow — default для legacy/unknown, не универсальная; Phase 0 — календарная семантика, scheduler/reminders — с Phase 1. Migration cost: 0.

**ADR-7 analytics events (NEW table + log_event).** Chosen: одна таблица events + хелпер; без шины/ETL. Why: 12 метрик стратегии умещаются в JSON-props; SQLite достаточно. Rejected: event-bus, отдельная аналитика. Migration cost: 0.

**ADR-8 Irisochka LLM integration (EXTEND, 1 функция).** Chosen: тело `_gemini()` → LLMFactory; публичные сигнатуры без изменений; образ не трогаем. Why: единственный обход фабрики; минимальный diff. Rejected: полная character-переработка (Phase 3). Migration cost: 0.

## 18. Minimal Change Strategy

| Компонент | Классификация | Действие |
|---|---|---|
| bot_handlers/diet_picker.py | **EXTEND** | после выбора: `planner.create_program()` + `create_first_plan()`; heuristics/extractor не трогать |
| bot_handlers/cabinet.py + picker FSM | **MERGE** (без переписывания) | единая точка входа /start; сохранение restrictions/activity на месте |
| modules/recipes/engine.py, prompt_builder.py | **KEEP** | без изменений; context-builder подмешивает поля профиля сверху |
| modules/fitness/engine.py | **EXTEND** | сигнатура `generate_exercises(meal, diet_mode, profile=None)`; промпт дополняется при profile |
| planner/ (модуль) | **NEW** | programs.py, plans.py, context.py; ~3 файла, только вызовы aiosqlite с timeout=30 |
| user_profiles | **EXTEND** | +3 колонки (restrictions/activity/timezone) — аддитивный ALTER по паттерну puhlyash_settings |
| meal_state/weekly_plans/diet_programs/events | **NEW** | по ADR-1/2/3/7 |
| meal_scheduler.py (cron-модуль) | **DEPRECATE** | отвязать от main.py в Phase 1 (Phase 0 — только пометить); файл не удалять |
| bot_handlers/schedule.py | **DEPRECATE (уже)** | не трогать в Phase 0 |
| api/miniapp_router.py | **DISABLE (решение владельца, 2026-09-12)** | исключить включение miniapp-роутов при старте API; initData-валидация — отдельная задача до повторного включения (не в Phase 0) |
| modules/puhlyash/irisochka.py | **EXTEND** | `_gemini()` → LLMFactory |
| reactions/diet_master/pipeline | **KEEP** | без изменений |
| shopping_lists/fridge_sessions/diary_entries/recipe_sessions | **KEEP (legacy)** | не трогать, не удалять (правило платформы) |

Запрещено: «перепишем diet_picker правильно» — только точечные вставки.

## 19. Migration Strategy

- **Без destructive migration:** все 4 таблицы — `CREATE TABLE IF NOT EXISTS` в едином `database.py`-скрипте (или отдельной миграции v3, применяемой при старте — конвенция init_db уже идемпотентна). 3 ALTER'а профиля — аддитивные, идемпотентные (проверка PRAGMA table_info перед ALTER — паттерн puhlyash_settings).
- **Старые пользователи (2 чел.):** профиль остаётся валидным (поля не переезжают). После деплоя: при первом `/start` мягко доспрашивается restrictions/activity (одна FSM-ветка) → создаётся program+plan. До этого reminder-флоу работает как сегодня (fallback §11) — **ничего не ломается**.
- **active_diet_mode:** остаётся (fitness его читает); параллельно создаётся diet_program. Dual-write НЕ нужен: это разные смыслы (hint vs домен).
- **Существующие recipes/reactions:** остаются; recipe_id в meal_state — nullable, старые рецепты не трогаем.
- **Backfill:** не нужен (истории программ нет — нечего переносить; докажено: диеты никогда не сохранялись).
- **Dual-read:** не нужен (новые сущности не имели старого источника). **Dual-write:** не нужен (см. active_diet_mode).
- **Legacy-удаление:** meal_scheduler-отключение в Phase 1; schedule.py и мёртвые таблицы — не раньше Phase 2+; никогда без явного указания владельца.

**Итог: migration не нужна в строгом смысле** — только идемпотентное создание NEW-объектов + 3 аддитивных колонки; откат = удаление новых таблиц (на проде 2 пользователя, история не теряется).

## 20. Implementation Order (порядок будущей реализации, не реализуем)

| # | Шаг | Why now | Depends on | Files | DB impact | Risk | Tests | Rollback |
|---|---|---|---|---|---|---|---|---|
| 0 | Preconditions: бэкап БД, снапшот кода, ветка + проверка SQLite-версии/partial unique indexes на копии БД (**выполнено 2026-09-12: SQLite 3.45.1, PARTIAL_UNIQUE_OK** — повторить на копии прод-БД перед деплоем) | безопасность | — | — | — | — | — | деплой старой версии; таблицы безвредны |
| 1 | planner-модуль (programs/plans/context: get_today_meals по цепочке PATCH-2; отдельные контекст-сборщики PATCH-6; даты только через tz-хелпер) | ядро | 0 | planner/*.py NEW | — | низкий | unit | git revert |
| 2 | Схема: 4 таблицы + 3 колонки + индексы **включая оба обязательных partial unique index** (идемпотентно, в init_db-потоке) | данные | 1 | database.py | +4T +3C +2 idx | низкий | schema-test (+тест инвариантов) | DROP TABLE (безвредно) |
| 3 | diet_picker EXTEND: LLM → validation → **BEGIN TX → persist program/plan/meal_state/events → COMMIT** (LLM вне транзакции, PATCH-5); сохранение restrictions/activity в FSM-шагах; meal_state создаётся только для фактических слотов (PATCH-4) | замыкание памяти | 1,2 | diet_picker.py | пишет NEW | средний (LLM-таймауты — но БД вне транзакции) | unit+E2E `--fast` | revert |
| 4 | context-builder подключение: fitness EXTEND + recipes passthrough | персонализация | 1,2 | fitness/engine.py, planner/context.py | — | низкий | unit | revert |
| 5 | Irisochka → LLMFactory | безопасность | — (независим) | irisochka.py | — | низкий | смоук реального вызова | revert |
| 6 | miniapp: DISABLE роутов (решение владельца; без initData-валидации в Phase 0) | security | — | точка include_router miniapp (api.py) | — | низкий | import/смоук API | revert |
| 7 | events + log_event в точки §14 | метрики сразу | 2 | planner/events.py + хендлеры | +1T | низкий | unit | revert |
| 8 | E2E обновление: программа сохранена, план на даты [start_date..end_date], meal_state только по фактическим слотам, каноническая цепочка get_today_meals работает | DoD | 3,7 | tests/e2e_diet_picker.py | — | низкий | e2e | — |
| 9 | Verify: рестарт, health, журнал без PII | выпуск | все | — | — | — | ручной чеклист | — |

(Schedule/reminder-переключение — **не входит** в Phase 0, это Phase 1 с ADR-4; Phase 0 только создаёт meal_state при создании плана.)

## 21. Parallel Work

**SERIAL CRITICAL PATH:** 0→1→2→3→(8,9). Шаг 3 — единственный содержательно-рискованный.

**PARALLEL SAFE:** (а) Irisochka-fix (5) — независим; (б) security miniapp (6) — независим; (в) events-инфраструктура (7) — после схемы, параллельно 3. Искусственный параллелизм не создаём: для одного исполнителя всё серийно за 3–4 сессии.

## 22. Test Strategy

**Existing (FACT):** test_puhlyash (persona-sync), test_vault_integration, e2e_diet_picker (FSM+FakeSession+temp-DB, `--fast`).

**Required для Phase 0 (все — на temp-копии БД, паттерн e2e):**
1. создание программы (active-инвариант: вторая программа → старая replaced);
2. ownership (чужой tg_id не видит программу/план);
3. сохранение weekly plan (7 дней, JSON-структура валидна);
4. plan→meal связь (meal_state создан **только для фактически присутствующих в плане слотов** — PATCH-4; UNIQUE(plan_id, day_date, meal_slot) не даёт дублей);
5. context-сборщики (build_diet_context / build_recipe_context / build_fitness_context) отдают только поля своего allowlist'а (PATCH-6), включая новые колонки; health_notes не входит ни в один;
6. **старый пользователь** (профиль без restrictions/activity/timezone → онбординг-доспрашивание, reminder-fallback работает);
7. повторный онбординг (профиль обновляется, программа replaced, история цела);
8. повторная генерация плана (архив предыдущей недели сохранён);
9. duplicate prevention (повторный «Подбирай!» не создаёт вторую active-программу — проверка **физического** отклонения IntegrityError от partial unique index, не только кодовой проверки);
9a. календарные границы (start_date/end_date: end_date=start_date+6; дата дня i = start_date+i; всё в tz пользователя);
9b. каноническая цепочка «что есть сегодня» (get_today_meals: при замене/архиве программы запрос не возвращает старые meal_state);
9c. транзакционная дисциплина (LLM-фейл до BEGIN — БД не тронута; фейл внутри TX — полный rollback, без частичных записей);
9d. meal_state-семантика (день без snack в плане → нет snack-записи в meal_state; snack не числится пропущенным);
10. timezone (day_date соответствует tz профиля; МСК-дефолт);
11. invalid Telegram identity (miniapp без initData → 401/отказ);
12. security boundaries (SQL-инъекция в tg_id — параметризованные запросы везде);
13. LLM failure (мок фабрики падает → эвристика сохраняет план со source='heuristic'; БД **не** находится в открытой транзакции — PATCH-5);
14. retry/partial failure (plan создан, program упал → транзакционность/компенсация);
15. rollback (DROP новых таблиц не ломает старый флоу).

**Ключевой принцип:** тесты проверяют **сохранение canonical state** (программа/план/meal_state в БД), а не только happy-path ответов.

## 23. Phase 0 DoD (проверяемый)

- [ ] Пользователь имеет canonical profile: единый онбординг, restrictions/activity/timezone сохраняются
- [ ] Active diet persistent: выбор → `diet_programs(status='active')`, переживает перезапуск
- [ ] Weekly plan persistent: `weekly_plans` с 7 днями; прошлая неделя archived
- [ ] Planned meals addressable: на вопрос «что должно быть съедено сегодня?» система отвечает **канонической цепочкой** `user → active diet_program → active weekly_plan → meal_state(plan_id, day_date=today)` (planner.get_today_meals) — не прямым запросом по tg_id+дата
- [ ] Календарные границы: weekly_plans.start_date/end_date заполнены в tz пользователя; end_date = start_date + 6 дней
- [ ] meal_state = только фактические слоты плана (нет искусственных snack-записей)
- [ ] DB-инварианты физически активны: оба partial unique index созданы и проверены тестом IntegrityError
- [ ] Transaction discipline: LLM-вызовы вне транзакций сохранения (LLM → validation → BEGIN → persist → COMMIT)
- [ ] Profile reaches generators: fitness/recipes/picker получают context-builder
- [ ] Existing recipe system works: recipes/reactions-флоу не изменён (регресс-тест)
- [ ] Irisochka uses LLMFactory: raw urllib удалён из кода (не из файла)
- [ ] No critical identity vulnerability: miniapp за initData или отключён
- [ ] Existing users not broken: 2 текущих профиля работают, reminder-fallback активен
- [ ] Tests pass: список §22 зелёный локально + E2E на whimco
- [ ] Migration reversible: DROP новых таблиц возвращает старое поведение
- [ ] Logs contain no sensitive data: events/логи без текстов сообщений и health-данных
- [ ] Analytics live: события Phase 0 (onboarding_started/completed, diet_program_created, plan_created, plan_saved, plan_viewed, llm_call) пишутся с первого дня; события Phase 1 (reminder_sent/meal_reaction/…) в Phase 0 не пишутся
- [ ] Времена разделены: events.ts = UTC, meal_state.day_date = локальная дата пользователя; ни один код не выводит «сегодня» из ts
- [ ] health_notes не передаются ни одному генератору и не попадают в events/логи (allowlist PATCH-6 активен)

## 24. Failure Modes (как реализовать Phase 0 неправильно)

| # | Failure | Why likely | Detection | Prevention |
|---|---|---|---|---|
| 1 | Duplicate SoT: диета пишется и в diet_programs, и в «active_diet_mode как диету» | привычка к старому полю | grep-аудит писателей | ADR-1: active_diet_mode = hint only; в коде один writer |
| 2 | Hidden legacy state: FSM-память продолжает считаться «планом» | код старый остаётся | code review шага 3 | после сохранения — state.update_data(diets=[]) и чтение из БД |
| 3 | Profile fields stored but ignored (снова) | паттерн уже был (weight/location) | тест №5 | context-builder = единственная точка чтения для генераторов |
| 4 | Plan generated but not persisted (частично: план в БД, meal_state нет) | две записи в разных местах | тест №4 | одна функция planner.create_program_and_plan(), транзакция |
| 5 | Persisted plan не связан с reminder | reminder-системы две | grep по _fire | Phase 0 не трогает reminder; Phase 1 — только через meal_state (ADR-4) |
| 6 | Reaction attached to recipe instead of planned meal | соблазн переиспользовать reactions | схема-ревью | ADR-4 зафиксирован; meal_state.status |
| 7 | Timezone bug: day_date по UTC/серверу | datetime.now() привычка | тест №10 | zoneinfo(tz профиля) в одном месте planner |
| 8 | Duplicate plans (двойной тап «Подбирай!») | FSM double-fire | тест №9 | partial unique index (физическая линия) + идемпотентность create (кодовая линия) |
| 8a | Ложный «пропущенный приём»: искусственные snack-записи в meal_state считаются пропущенными | привычка создавать 7×4 | тест №9d | meal_state создаётся только для слотов, реально присутствующих в плане (PATCH-4) |
| 8b | Смешение времён: «сегодня» вычислено из events.ts (UTC) вместо локальной даты | удобство одного поля | grep по использованию ts | инвариант PATCH-10: day_date только из tz-хелпера; ts — только для абсолютного порядка событий |
| 8c | Прямой запрос meal_state по (tg_id, day_date=today) мимо канонической цепочки | удобство одного WHERE | тест №9b | PATCH-2: чтение только через planner.get_today_meals (user → active program → active plan → meal_state) |
| 9 | Orphaned records: weekly_plans без программы | частичный фейл | тест №14 | транзакция/порядок вставок в planner |
| 10 | User isolation failure: чужой план читается | нет FK, ручные WHERE | тесты №2/№12 | ВСЕ запросы planner — WHERE tg_id=?; тест на кросс-доступ |
| 11 | LLM context leakage: health_notes утекают в логи/чужие промпты | копипаста контекста | аудит логов | контекст только в промпт пользователя; логи — метаданные |
| 12 | Migration destroying history: «почистим мёртвые таблицы» | желание навести порядок | — | Phase 0: ничего не удалять; legacy-очистка — отдельное решение владельца |

## 25. Architecture Diagrams

**Current → Target data flow:**

```
Telegram
  ↓
User/Profile (user_profiles, +3 поля)
  ↓                                  [Phase 0 NEW]
Diet Program (diet_programs) ←── diet_picker EXTEND
  ↓
Weekly Plan (weekly_plans, JSON days)
  ↓
Planned Meal (meal_state, UNIQUE день+слот)
  ↓
Reminder (meal_schedule_v2, Phase 1: читает meal_state)
  ↓
Reaction (meal_state.status; reactions — вкусы)
  ↓
[Phase 2] Adaptation → Next Weekly Plan
  ↓
[Phase 3] Character Memory
```

**LLM flow (существующий + context-builder):**

```
Profile (+restrictions/activity/timezone)
  ↓
Context Builder (planner/context.py, NEW — единая точка)
  ↓
LLMFactory (KeyPool 3G+6Q, CircuitBreaker, fallback)
  ↓
Model (gemini-3.1-flash-lite)
  ↓
Validated Result (_extract_json / эвристики — как есть)
  ↓
Domain (planner → weekly_plans; recipes → recipes)
```

## 26. Critical Review (несогласие со стратегией — по пунктам)

1. **Технически сомнительное в стратегии:** метрика M12 (LLM cost/юзер) требует токен-учёта, которого LLMFactory не отдаёт (FACT — интерфейс возвращает текст). В Phase 0 — только latency/ok-факты; стоимость останется оценочной до доработки фабрики (вне Phase 0).
2. **Стратегия предполагает данные, которых нет:** «return after missed meal» (M10) предполагает знание факта пропуска до его фиксации; в Phase 0 пропуска не фиксируются автоматически (только timeout Phase 1) — метрика заработает не раньше Phase 1. Аналогично week completion требует полной записи статусов — частично Phase 1.
3. **Переоценка архитектуры:** стратегия предполагает, что «reminder читает план» — почти готово; FACT: reminder-систем две и обе не знают о плане; консолидация — нетривиальный шаг Phase 1, недооценённый по объёму.
4. **Риск перепроектирования:** соблазн нормализовать days/meals (ADR-2) и построить behavior-агрегаты заранее — отклонён; JSON-дни + SQL-агрегаты по meal_state достаточны.
5. **Риск нового legacy:** новые таблицы повторят судьбу diary/shopping (созданы-заброшены), если meal_state не получит writer'а в том же PR — поэтому шаги 3 и 8 в §20 неразрывны.
6. **Owner decisions — ОБА РЕШЕНЫ ВЛАДЕЛЬЦЕМ 2026-09-12:** (а) miniapp = DISABLE в Phase 0, initData-валидация НЕ реализуется (отдельная задача до повторного включения роутов); (б) timezone = `user_profiles.timezone` канонический, default Europe/Moscow для legacy/unknown, не универсальная; Phase 0 — только календарная семантика, scheduler/reminders — с Phase 1 (ADR-6 подтверждён). Решение по reminders также зафиксировано в Phase 0 (ADR-4, PATCH-8). Незакрытых owner decisions не осталось.
7. **Можно отложить:** per-user tz в APScheduler, нормализация дней, character_memory-схема,(events-ретеншн).
8. **Категорически нельзя в Phase 0:** трогать reminder-флоу, удалять legacy, нормализовать дни, строить адаптацию, менять образ Ирисочки, деплоить без бэкапа БД.
9. **Недоказанные архитектурные решения:** JSON-дни выдержат ли Phase 2-адаптацию (вероятно да — json_extract; проверить при первом aggregate-запросе). Partial unique index — доказано (SQLite 3.45.1 на whimco, PARTIAL_UNIQUE_OK, 2026-09-12); перед деплоем — повторный прогон на копии прод-БД (§20-0).
10. **Самое опасное техническое допущение:** что «день» определён. Без tz-решения meal_state.ration дня расползается: план на 7 дней от даты X в МСК при юзере в другом tz даёт сдвиг всех приёмов. ADR-6 закрывает, но требует дисциплины: **вся работа с датами только через planner-хелпер.**

## 27. Product Strategy Sanity Check

Цепочка hypothesis→behavior→state→implementation→event→metric→decision, построчно:

| Hypothesis (Stage 2) | Behavior | Domain state | Implementation (Phase 0) | Event | Metric | Decision |
|---|---|---|---|---|---|---|
| H1 «нужна организация, не диета-текст» | выбирает программу, возвращается | diet_programs + weekly_plans (с границами недели) | шаги 1–3 | diet_program_created, plan_saved | M1–M3, D1 | Phase 0 exit |
| H9/H5 «лёгкий дневник/меньше решений» | тапает съел/заменил | meal_state.status | схема создаётся Phase 0, writer Phase 1 | meal_reaction | M5–M7 | Phase 1 exit |
| H2 «адаптация ценнее» | живёт 2+ недели | archived plans + meal_state | требования §13 | (Phase 2) | M7-динамика | Phase 2 exit |
| H3/H10 «персонаж+память» | реагирует на персонажа | character_memory (Phase 3) | не в Phase 0 | character_* | M9–M10 | A/B §12 |

**«Система помнит пользователя» технически означает (Phase 0):** (а) профиль canonical и не теряет поля; (б) выбор диеты → строка в БД со статусом active; (в) план → строки weekly_plans+meal_state с датами; (г) перезапуск процесса не меняет ответов системы на вопросы «какая у меня диета? что мне есть сегодня?». Если хотя бы одно из (а)–(г) ложь — «памяти» нет, есть имитация.

**«Система адаптирует питание» станет правдой, когда существуют:** meal_state-история ≥1 недели (что планировали/что произошло), archived планы (с чем сравнивать), profile context у генератора следующей недели, и правило адаптации, объяснимое в выводе. Phase 0 обеспечивает первые три; без них слово «адаптация» — маркетинг.

**Разорванных звеньев в цепочке нет**, но два звена отложены (meal_reaction-writer и M10) — честно помечены как Phase 1.

## 28. Final Recommendation

Phase 0 реализуем как **additive миграцию без разрушения**: 4 таблицы, 3 колонки, 1 новый модуль (planner), 4 EXTEND-точки, 1 security-функция, 1 фикс Ирисочки. Порядок §20 — единственный безопасный (сначала данные и модуль, потом хендлеры, tests/e2e — вместе с шагом 3). Открытых вопросов владельцу нет — оба решены 2026-09-12: miniapp = DISABLE в Phase 0 (initData-валидация — отдельная задача до повторного включения); timezone = `user_profiles.timezone` канонический, default Europe/Moscow, не универсальная (ADR-6 подтверждён). **SAFE TO PROCEED: YES** — реализация начинается только после отдельного подтверждения (правило Stage 2.5).

## 29. Change Log (Stage 3 Architecture Patch, 2026-09-12)

Источник: `promts/3.md`. Все 10 обязательных исправлений внесены; противоречащие формулировки удалены; по каждому решению в документе осталась ровно одна версия.

| # | Patch | Где в документе |
|---|---|---|
| 1 | weekly_plans: календарные границы start_date/end_date (ISO 'YYYY-MM-DD', вычисляются в tz пользователя), инвариант end_date = start_date + 6; неделя не восстанавливается косвенно через meal_state | §7 (схема + «Календарная семантика»), §20-8, тест 9a, DoD |
| 2 | SoT «что есть сегодня»: каноническая цепочка user → active diet_program → active weekly_plan → meal_state(day_date=today); прямой запрос `meal_state WHERE tg_id=? AND day_date=today` — НЕ источник истины | §8 (ADR-3), §11, §20-1, тест 9b, FM 8c, DoD |
| 3 | Физические DB-инварианты обязательны (не «recommended/optional»): оба partial unique index; implementation precondition выполнен — SQLite 3.45.1, PARTIAL_UNIQUE_OK | §6, §7, §20-0/2, тест 9, DoD |
| 4 | meal_state = materialized state только для фактически запланированных meal slots (без шаблона 7×4, без искусственного snack) | §8 (PATCH-4), §20-3, тесты 4/9d, FM 8a, DoD |
| 5 | Запрещена транзакция вокруг LLM-вызова: LLM → validation → BEGIN → persist → COMMIT; при ошибке LLM БД вне открытой транзакции | §8 (PATCH-5), §20-3, тесты 9c/13, DoD |
| 6 | Allowlist профиля по генераторам (3 отдельных контекст-сборщика); health_notes не передаются ни одному генератору автоматически, не попадают в events/логи | §9 (PATCH-6), §15, FM 11, тест 5, DoD |
| 7 | Timezone-контракт разделён по фазам: Phase 0 — календарная семантика (start_date/end_date/day_date/«сегодня»); Phase 1 — дополнительно scheduler/reminders; Europe/Moscow — default для legacy/unknown, не универсальная | ADR-6, §9, §11 |
| 8 | ADR-4 однозначен: решение (meal_schedule_v2 = целевая единственная reminder-система) принимается в Phase 0; runtime-миграция/deprecation legacy scheduler — Phase 1; в Phase 0 scheduler не ломается | §11, ADR-4, §2.3, §26-6 |
| 9 | События разделены: Phase 0 — минимальный набор (onboarding_started/completed, diet_program_created, plan_created, plan_saved, plan_viewed, llm_call); reminder/meal-события — только Phase 1 | §14, §27, DoD |
| 10 | Инвариант времени: events.ts = UTC (абсолютный порядок событий); meal_state.day_date = локальная календарная дата пользователя; «сегодня» никогда не выводится из ts | §14 (PATCH-10), FM 8b, DoD |

**Консистентность (финальный проход):** уточнены места со старыми формулировками — §2.3 («обязательно к разрешению» → решение зафиксировано PATCH-8; формулировка заменена), тест №5 (единый build_profile_context → три allowlist-сборщика из PATCH-6), §15 Health data, §26-6 (reminders больше не owner decision), §26-9 (partial unique index доказан), FM 8c добавлен. Проверены разделы: SoT, ADR, schema, invariants, migration, implementation order, tests, DoD, failure modes, architecture gate, границы Phase 0/Phase 1 — противоречащих версий одного решения не осталось.

**NEW BLOCKER:** не обнаружен. Единственные открытые пункты перед реализацией — 2 owner decisions (§28): судьба miniapp-роутов и дефолт timezone.

**СТАТУС: ARCHITECTURE PATCH: READY FOR GATE**

## 30. Architecture Gate (2026-09-12)

**Owner decisions (зафиксированы владельцем 2026-09-12, отражены в §15, §18, §20, §26, §28):**

1. **Mini App:** Phase 0 = DISABLE незащищённых miniapp-роутов. initData-валидация НЕ реализуется в Phase 0. Повторное включение — только после отдельной задачи валидации.
2. **Timezone:** `user_profiles.timezone` — канонический timezone пользователя; для legacy/unknown — default `Europe/Moscow`; Europe/Moscow НЕ универсальная tz. Phase 0 использует tz только для календарной семантики; scheduler/reminders — начиная с Phase 1.

| # | Проверка Gate | Раздел документа | Результат |
|---|---|---|---|
| 1 | SoT и ownership | §4, §8, ADR-1/ADR-3 | OK |
| 2 | Цепочка user_profiles → diet_programs → weekly_plans → meal_state | §5, §8 (PATCH-2) | OK |
| 3 | Календарные границы weekly plan (start/end_date, инвариант +6) | §7 (PATCH-1) | OK |
| 4 | Active-state DB invariants (обязательные partial unique indexes) | §6, §7 (PATCH-3) | OK |
| 5 | meal_state только для фактически существующих meal slots | §8 (PATCH-4) | OK |
| 6 | LLM вне DB transaction | §8 (PATCH-5) | OK |
| 7 | Profile context allowlists (3 раздельных сборщика) | §9 (PATCH-6) | OK |
| 8 | Отсутствие автоматической передачи health_notes | §9, §15, FM-11 | OK |
| 9 | Timezone contract (разделение Phase 0/1) | ADR-6 (PATCH-7) | OK — подтверждён владельцем |
| 10 | Reminder ADR (однозначная формулировка) | §11, ADR-4 (PATCH-8) | OK |
| 11 | Phase 0 / Phase 1 boundaries | §11, §14, ADR-4/ADR-6 | OK |
| 12 | Events (минимальный набор Phase 0, ts=UTC ↔ day_date) | §14 (PATCH-9/10) | OK |
| 13 | Mini App security | §15 (решение владельца: DISABLE) | OK |
| 14 | Migration strategy (additive, идемпотентно) | §19 | OK |
| 15 | Rollback (revert + DROP новых таблиц) | §19, §20, §22-15 | OK |
| 16 | Tests (15 сценариев §22) | §22 | OK |
| 17 | DoD (проверяемый) | §23 | OK |
| 18 | Failure modes | §24 | OK |

Противоречий и новых blockers не обнаружено (NEW BLOCKER: нет). Новые архитектурные сущности не добавляются.

**ARCHITECTURE GATE: GO**

## 31. Product Positioning Impact (аудит promts/6, 2026-09-12)

Итог аудита Product Positioning + Architecture Impact Review (проходы 1+2, E3): **GO WITH CHANGES**, C-2 impact = **DOCUMENTATION ONLY** — ни одна таблица, индекс, колонка, функция planner или тест не требуют изменений. Зафиксированные правки (CP-1…CP-5, применены 2026-09-12):

**CP-3 — Границы Product Gates и формулировка миграций.** Authorship рецептов, статусы и экономика — будущие Product Gates, не Phase 0. Миграционная формулировка (каноническая, вместо «не требует миграций вообще»): **«C-2 не требует изменений схемы; будущие домены могут потребовать аддитивных миграций после соответствующих Product Gates.»**

**CP-4 — 🔥: единственная формулировка.** Отдельной второй валюты 🔥 НЕТ; активность = обычные события/стрики/derived-метрики (OWNER, promts/5.md §13 «🥞 VS 🔥»). Открытый вопрос «🔥 currency vs events/streaks» снят; противоречащей версии не остаётся.

**CP-5 — D30 ≥15% переклассифицирован.** Источник — стратегия (`promts/2.md:600,645`), уровень DOCUMENT. Это НЕ owner decision; порог подтверждается или заменяется владельцем на monetization Product Gate. Без явного решения владельца не использовать как подтверждённый gate.

**CP-1 / CP-2 — позиционирование и политика событий.** См. docstrings: `planner/__init__.py` (Nutrition / Planning domain module, не ядро продукта) и `planner/events.py` (будущие event-имена — аддитивные доменные префиксы в generic `events`, без таблиц на домен; политика ≠ гарантия неизменности схемы).

Источники: OWNER `promts/5.md` (§13, оговорка про числа экономики), DOCUMENT `promts/2.md` (D30), аудит-отчёт 2026-09-12 (реестры VF/VI/VD/VC/VU).
