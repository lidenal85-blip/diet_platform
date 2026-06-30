# 📋 TEAM NOTES — Diet Platform «Пухляш»

> Файл для синхронизации между разработчиками.
> Обновляй при каждом значимом изменении.
>
> 📌 См. также `PRODUCT_BACKLOG.md` — продуктовые требования от владельца
> (рецепты, диеты, фитнес, локализация, маскоты) — 9 эпиков, фазировано.

---

## 🐱 МАСКОТЫ ПРОЕКТА

### Пухляш (основной)
- Рыжий пухлый кот с мышонком-другом
- **Характер:** саркастичный подкольщик, но заботливый
- **Зона:** питание, диеты, тренировки, расписание
- **Tone of voice:** «Ну ты и обжора... но я помогу 😏»
- Арт: см. `/assets/mascots/puhlyash_*.jpg`

### Ирисочка (в разработке)
- **Характер:** эмпатичная, жизнерадостная, добрая, мудрая советчица
- **Зона:** сладкое, десерты, читмил, утешение
- **Tone of voice:** «Ты молодец! Один кусочек не страшно 🍬»
- Статус: **персонаж утверждён, реализация не начата**
- Нужно: создать `modules/irisochka/persona.py` по образцу `modules/puhlyash/persona.py`

---

## ✅ CONFLICT-01 — ИСПРАВЛЕНО ОКОНЧАТЕЛЬНО (2026-06-30) — Ушли от Pyrogram вообще

**История вопроса:** сначала был конфликт за Pyrogram session между diet_platform
и den4ik-claude (см. историю ниже — Userbot Relay от 2026-06-19). 2026-06-30
den4ik-claude мигрировал на новый файл `leviathan_hub_bot.py` («4 modes:
AUTO/CORE/FORGE/HERALD»), который вообще не использует Pyrogram — Userbot
Relay перестал отвечать (`/opt/den4ik-claude/userbot_relay.py` остался на
диске, но никем не запускается).

**Решение владельца:** Pyrogram/userbot больше не нужен вообще.
`modules/notifier/sender.py` переписан повторно — теперь использует
**собственный aiogram Bot** diet_platform (свой `TELEGRAM_BOT_TOKEN` из `.env`),
никакой зависимости от den4ik-claude/Userbot Relay больше нет. Короткоживущий
`Bot()`-инстанс на каждую отправку (стандартная практика aiogram для одиночных
отправок из фоновых задач, не связанных с long-polling в bot.py).

**Проверено:** `send_notification()` → `True`, реальное сообщение
дошло в Telegram без участия den4ik-claude.

**Не удалено намеренно:** `userbot_relay_token` в `config.py` и `USERBOT_RELAY_TOKEN`
в `.env` оставлены на месте (безвредны, но уже нигде не используются) —
быстрый rollback возможен, если понадобится.

**Старая версия файла:** `modules/notifier/sender.py.bak` (httpx → Userbot Relay).

---

## 📜 ИСТОРИЯ: CONFLICT-01 — Userbot Relay (2026-06-19, устарело, см. выше)

**Была проблема:** `diet_platform` и `/opt/den4ik-claude/` (оба проекта владельца,
подтверждено) использовали один и тот же Pyrogram session-файл
(`/opt/telegram-agent-book/my_account.session`, SQLite). Два процесса одновременно
открыть её не могли → 100% push-уведомлений о приёмах пищи падали с `database is locked`.

**Решение — Userbot Relay.** Почему не полный мердж в один процесс:
den4ik-claude использует Pyrogram глубоко (dialogs, history, create_channel,
live-watcher `@papp.on_message`) — полное слияние увеличило бы blast radius
(баг в публичном diet-боте оказался бы в одном процессе с `systemctl stop` на все
сервисы). Вместо этого вынесли ровно один общий ресурс — саму Telegram-сессию.

**Архитектура:**
- `den4ik-claude` остаётся **единственным владельцем** Pyrogram-сессии, ничего
  в его функционале не изменилось
- Внутри его же `asyncio.gather()` в `main()` запущен мини-FastAPI на
  `127.0.0.1:8190` (новый файл `/opt/den4ik-claude/userbot_relay.py`)
- `diet_platform/modules/notifier/sender.py` полностью переписан: теперь это тонкий
  httpx-клиент, дёргающий `POST http://127.0.0.1:8190/relay/send` — без
  собственного Pyrogram Client. Сигнатура `send_notification()` не изменилась —
  вызывающий код (scheduler/meal_scheduler.py) править не пришлось
- Авторизация: заголовок `X-Relay-Token`, одинаковый с обеих сторон —
  `RELAY_TOKEN` в `den4ik-claude/bot.py` и `USERBOT_RELAY_TOKEN` в `diet_platform/.env`

**Проверено end-to-end:**
- `GET http://127.0.0.1:8190/health` → `{"status":"ok"}`
- `send_notification()` из diet_platform → `True`, сообщение реально дошло в Telegram
- Неверный `X-Relay-Token` → HTTP 403 (авторизация работает)
- `fuser /opt/telegram-agent-book/my_account.session` → ровно ОДИН PID (den4ik-claude)

**Найдено и исправлено по ходу:** `parse_mode="html"` (строкой) вызывал HTTP 502 —
Pyrogram ждёт объект `pyrogram.enums.ParseMode`, а не строку. Добавлен маппинг
в `userbot_relay.py` (`html→ParseMode.HTML`, `md→ParseMode.MARKDOWN`).

**Изменённые файлы:**
- `/opt/den4ik-claude/userbot_relay.py` (новый)
- `/opt/den4ik-claude/bot.py` (+import, +`RELAY_TOKEN`, +`run_relay_server()` в `gather()`)
- `/opt/diet_platform/modules/notifier/sender.py` (полностью переписан, бэкап сохранён)
- `/opt/diet_platform/building_blocks/config.py` (+`userbot_relay_token`)
- `/opt/diet_platform/.env`, `.env.example` (+`USERBOT_RELAY_TOKEN`)

---

## ⚠️ НАЙДЕНО ПОПУТНО, НЕ ИСПРАВЛЕНО — aiogram getUpdates конфликт (den4ik-claude)

Бот `@den4ik_claude_bot` (токен `8933899236:...`) постоянно ловит `TelegramConflictError`:
```
Telegram server says - Conflict: terminated by other getUpdates request
```
Это **не связано** с Userbot Relay выше — разные протоколы
(aiogram = Bot API getUpdates, Pyrogram = MTProto userbot, не пересекаются).

**Диагностика:**
- На этом сервере только один процесс с этим токеном (`den4ik-claude.service`)
- `getWebhookInfo` → webhook пустой, `pending_update_count: 0`
- Значит где-то **вне этого VPS** ещё один процесс держит getUpdates на
  том же токене (другой сервер, забытая screen/tmux/docker-сессия)
- Проблема была и ДО моих правок (839 попыток за ~70 минут до рестарта) —
  не моя работа

**Что проверить владельцу:** нет ли забытой копии этого бота на другом
VPS/локальной машине/забытой docker/screen/tmux-сессии. Это не блокирует
Userbot Relay (он работает через Pyrogram, не через aiogram), но ломает обычные
Telegram-команды den4ik-claude.

---

## ✅ GitHub Push — РЕШЕНО (2026-06-20)

**Была проблема:** исходный PAT для `lidenal85-blip` был мёртв (401 Bad
credentials). Два других токена, которые пробовали вместо него —
`den4ikorm1985` и `lewinthinkman-wq` — это ДРУГИЕ GitHub-аккаунты. Оба валидные,
но имеют только `pull` на `lidenal85-blip/diet_platform` (репо публичный,
поэтому `git fetch` работал даже с мёртвым токеном лиденал85-blip — это
анонимное чтение, не авторизация), а `push` всё равно даёт 403 даже с
валидным токеном. Добавить collaborator тоже не получилось этими же
токенами — `lidenal85-blip` оказался обычным пользователем (не организацией),
админ-действия над репо доступны только с валидным токеном самого `lidenal85-blip`.

**Решение:** владелец перевыпустил PAT из-под самого `lidenal85-blip`.
Проверено через `GET /user` (login совпал) и `GET /repos/.../diet_platform`
(`permissions.push: true`) перед пушем. Push прошёл, SHA на GitHub совпал с
локальным HEAD (`5a6a00c`).

**Важно на будущее:**
- При перевыпуске («Regenerate») GitHub всегда создаёт НОВУЮ строку токена —
  старое значение никогда не оживает повторным нажатием кнопки
- Рабочий токен сейчас вшит только в `git remote -v` (`.git/config`) — НЕ в коде,
  НЕ в истории коммитов (проверено `git grep` по HEAD перед пушем — чисто)
- При истечении/отзыве нового токена — входить именно в аккаунт `lidenal85-blip`
  (Settings → Developer settings → PAT), не в любой другой аккаунт на этом сервере

**Push #1 (5a6a00c):** Userbot Relay, BUG-01/02/03 фиксы, первый коммит ранее
untracked кода (bot_handlers/, api/, modules/fitness, notifier, puhlyash, reactions,
scheduler, recipes), TEAM_NOTES.md + PRODUCT_BACKLOG.md

---

### [FIXED и ПОДТВЕРЖДЕНО]
- BUG-01: `database is locked` (diet_platform.db) — `timeout=30` во все aiosqlite.connect()
  → сервис работает без рестартов (было 298 рестартов)
- BUG-02 (ROOT CAUSE): `EXTRACTION_PROMPT` содержал `{ }` из JSON-схемы → LLMFactory
  `prompt_engine.py` делал `.format(**kwargs)` и падал с `KeyError`. Промпт переписан
  без фигурных скобок
- BUG-03: Сессии зависали в `searching` — `_update_session_progress` теперь вызывается
  и в DLQ-ветке → все 7 сессий стали completed
- **CONFLICT-01** — Userbot Relay, см. выше. Уведомления снова работают
- Результат: pipeline произвёл 12 диет в diet_master (было 0)

### [Новое, не исправлено — вне этого VPS]
- aiogram getUpdates conflict у den4ik-claude — см. раздел выше

### [Открытые, не критичные]
- ISSUE-03: `urllib.request` (sync) в `recipes/engine.py`, `fitness/engine.py`, `puhlyash/persona.py`
  → блокирует event loop. ЧАСТИЧНО исправлено 2026-06-21 (J2 — chef_chat в
bot_handlers/recipes.py переведён на LLMFactory). Остались `modules/recipes/engine.py`,
`modules/fitness/engine.py`, `modules/puhlyash/persona.py` — большой рефактор, не тронуты намеренно
- ISSUE-04: Нет `__init__.py` в `search_gateway/`, `web_scraper/`, `diet_extractor/`, `diet_registry/`
- ISSUE-06: confidence_score низкий (0.15–0.35) из-за CircuitBreaker на Gemini/Groq в момент
  retry — fallback на эвристики. Не баг, но все 12 диет сейчас в pending_verification
  с низким confidence — модератору нужно вручную проверить перед публикацией
- ISSUE-07: outbox пуст — новых задач нет, ждём новых /search от пользователей
  чтобы проверить pipeline на живых данных
- J4 (из трассировки 2026-06-20): два независимых онбординга (diet_picker и cabinet)
  пишут в одну user_profiles — связано с G2 в PRODUCT_BACKLOG.md
- `modules/notifier/sender.py` (старая версия) использовал `logging.getLogger(__name__)`
  без настройки — в новой версии то же самое, не критично

---

## 🗄️ БАЗА ДАННЫХ

- Путь: `/opt/diet_platform/diet_platform.db`
- Режим: WAL (Write-Ahead Logging)
- Схема v1: `database.py`
- Схема v2 (доп. таблицы): `database_migration_v2.sql`
- **Таблицы:** search_sessions, outbox, dlq, web_snapshots, diet_drafts, diet_master,
  audit_log, user_profiles, meal_schedule, recipe_sessions, shopping_lists,
  fridge_sessions, recipes, reactions, diary_entries
- Реальные пользователи: 2 (tg_id: 7709651193, 8113236937)
- Диет в diet_master: 12 (все pending_verification, ждут модерации)

---

## 🏗️ АРХИТЕКТУРА

Краткое:
- FastAPI (port 8150) + aiogram3 бот «Пухляш» — единый процесс
- Pipeline: DuckDuckGo → httpx scraper → Gemini extractor → diet_registry
- Очередь: SQLite Outbox (статус-поллинг каждые 3с)
- LLM: Leviathan LLMFactory (14 ключей Gemini 2.5-flash, KeyPool + CircuitBreaker, fallback → Groq)
- Notifications: собственный aiogram Bot (без Pyrogram/Userbot Relay, см. CONFLICT-01 — 2026-06-30)
- Scheduler: APScheduler (timezone Moscow)

Связанные проекты на этом же сервере:
- `/opt/den4ik-claude/` — личный пульт управления всей инфраструктурой (сервисы,
  медиа-фабрика, вакансии, OWNER_ID-gated). Теперь также хостит Userbot Relay
  для diet_platform

---

## 🚀 ДЕПЛОЙ

```bash
systemctl status diet-platform den4ik-claude   # статус обоих

# ВАЖНО: обычный systemctl restart / kill --signal=SIGTERM иногда не убивает
# процесс полностью (видели: PID висел 'sleeping' после SIGTERM и системд
# считал сервис всё ещё active, новый start ничего не делал). Если обычный
# restart не помог, бей жёстко по PID (systemd сам поднимет благодаря Restart=always):
PID=$(systemctl show <service> -p MainPID --value); kill -9 $PID

# ОБЯЗАТЕЛЬНО после правки .py файлов:
find /opt/diet_platform -name '__pycache__' -exec rm -rf {} +
find /opt/den4ik-claude -name '__pycache__' -exec rm -rf {} +

journalctl -u diet-platform -f         # логи live diet_platform
tail -f /var/log/den4ik_claude.log     # логи live den4ik-claude (буферизуются, не сразу видно)
curl http://localhost:8150/health      # diet_platform healthcheck
curl http://127.0.0.1:8190/health      # Userbot Relay healthcheck
curl -X POST http://localhost:8150/api/v1/dlq/retry-all  # перезапуск DLQ
```

---

## 📅 CHANGELOG

### 2026-06-30 — Ушли от Pyrogram вообще (Claude / Leviathan Agent)
- Обнаружено: den4ik-claude мигрировал на leviathan_hub_bot.py, который не использует
  Pyrogram — Userbot Relay остался на диске, но никем не запускался. Уведомления падали
  с connection refused.
- Владелец решил: Pyrogram/userbot больше не нужен вообще — перевёл уведомления
  на собственный aiogram Bot diet_platform.
- `modules/notifier/sender.py` переписан второй раз (был httpx→Relay, стал
  прямым aiogram Bot()). Сигнатура `send_notification()` не менялась — вызывающий
  код не тронут.
- Проверено реальной отправкой: True, сообщение дошло без участия den4ik-claude.
- diet_platform теперь полностью независим от den4ik-claude для Telegram-функционала.

### 2026-06-21 — J1/J2/J3 фиксы + инцидент с den4ik-claude (Claude / Leviathan Agent)
- **Инцидент:** при рутинной проверке обнаружен `den4ik-claude` в статусе `failed`
  — явный `systemctl stop` 11 часов назад (вероятно через самого бота,
  не моя правка). `Restart=always` не сработал, т.к. стоп был осознанным, не
  крашем. Всё это время Userbot Relay был недоступен. Поднял, проверено —
  оба сервиса снова `active`.
- J1 исправлен: последний оставшийся `aiosqlite.connect()` без timeout (алиас `_DB`
  в meal_schedule_v2.py) — проверено `grep` по всему репо, больше ни одного случая
- J2 исправлен: «Шеф на телефоне» переведён с raw urllib+регекс-чтения .env на
  LLMFactory.execute_request() — смоук-тест прошёл с реальным ответом от Gemini
- J3 исправлен: убраны остаточные `print([DEBUG]...)` из recipes.py
- Зафиксировано новое требование в PRODUCT_BACKLOG.md — настраиваемая видимость
  блоков дашборда/напоминаний через профиль/кабинет (расширение E4)
- Сделана полная трассировка пользовательского пути по всему bot.py — найдены J1-J4

### 2026-06-20 — GitHub push решён (Claude / Leviathan Agent)
- Исходный токен `lidenal85-blip` был мёртв; два альтернативных токена
  (`den4ikorm1985`, `lewinthinkman-wq`) оказались чужими аккаунтами без push-доступа
- Владелец перевыпустил PAT из-под `lidenal85-blip` — push прошёл, подтверждено по SHA
- Попутно закоммичен весь ранее untracked живой код бота (впервые в git!)
- Расширен `.gitignore`: `*.bak_*`, `*.swp`
- Создан `PRODUCT_BACKLOG.md` — 9 эпиков продуктовых требований от владельца,
  фазировано на 4 фазы

### 2026-06-19, вечер — Userbot Relay (Claude / Leviathan Agent)
- Подтверждено владельцем: den4ik-claude — тоже его проект, можно изменять
- Рассмотрел полное слияние в 1 процесс — отклонён (разные bounded contexts,
  большой blast radius для публичного бота)
- Реализован **Userbot Relay**: den4ik-claude остаётся владельцем Pyrogram-сессии,
  diet_platform дёргает его через локальный HTTP (127.0.0.1:8190)
- CONFLICT-01 закрыт, проверено end-to-end и реальной отправкой
- По ходу найдена и не связанная проблема: aiogram getUpdates конфликт у den4ik-claude
  (источник вне этого VPS, предсуществовал до моих правок)

### 2026-06-19, 09:00 UTC — Повторный анализ (Claude / Leviathan Agent)
- Подтверждено: все 3 бага из предыдущей сессии исправлены и держатся 12+ часов
- Найден CONFLICT-01 — исправлен в этот же день вечером (см. выше)

### 2026-06-18 (Claude / Leviathan Agent)
- Проведён анализ проекта, зафиксированы маскоты: Пухляш + Ирисочка
- Исправлены баги: database locked, JSON/format KeyError (root cause), sessions stuck

### 2026-06-17 (Denis)
- init commit: Puhlyash diet platform — bot + FastAPI + Gemini pipeline

---

## ⚠️ ВАЖНО ДЛЯ НОВЫХ РАЗРАБОТЧИКОВ

1. **Не открывай aiosqlite.connect() без `timeout=30`** — будет database locked
2. **Не используй urllib.request в async функциях** — блокирует event loop
3. **Все LLM-вызовы** идут через `/opt/leviathan_engine/llm_factory.py`, не напрямую
4. **НИКАКИХ `{` `}` в промптах для LLMFactory** — он делает `.format(**kwargs)` внутри
5. **После правки .py файлов всегда чисти __pycache__** перед рестартом
6. **systemctl restart иногда виснет полностью** — проверяй PID и бей `kill -9` при необходимости
7. **Bot token и API keys** — только в `.env` / константах рядом с остальными секретами
8. **den4ik-claude и diet_platform — оба проекта владельца**, но разные по риску:
   den4ik-claude имеет `systemctl stop/start` над всеми сервисами — правь аккуратно
9. **Pyrogram больше не используется в diet_platform** (2026-06-30). Уведомления идут
   через собственный aiogram Bot (`modules/notifier/sender.py`). Не создавай
   зависимость от den4ik-claude/Userbot Relay для отправки сообщений снова.
10. **Маскот Пухляш** — саркастичный, но добрый. Ирисочка — мягкая и мудрая. Тон важен!
11. **GitHub push** — токен всегда должен быть из-под аккаунта `lidenal85-blip`,
    не из других аккаунтов на этом сервере — у них только `pull`. Перед pushом
    стоит сверить `permissions.push: true` через GitHub API