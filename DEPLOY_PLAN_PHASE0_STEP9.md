# DEPLOY PLAN — §20 step 9 (Phase 0 выпуск на whimco)

> Дата: 2026-09-15/16 · Статус: **ШАГИ A–E ВЫПОЛНЕНЫ — §20 STEP 9 ЗАВЕРШЁН** (деплой Phase 0 на whimco: код + схема + рестарт + верификация PASS). Owner-остаток: живые Telegram-проверки 6.4 / 6.6 / 6.7
> Основание: ARCHITECTURE_PHASE0_2026-09.md §20 (шаги 0–9), §19 (Migration Strategy),
> §23 (DoD), TEAM_NOTES.md «ДЕПЛОЙ» (restart-хрупкость), start_here/PASSPORT.md (команды),
> SERVER_ACCESS_WHIMCO.md (канонический SSH-доступ).
> Код к выпуску: 5 коммитов C-3 на `main` — `713c56b` (шаг 3) → `29f7292` (шаг 4) →
> `07ee3e1` (шаг 5) → `30a06eb` (шаг 6) → `9205cbf` (шаги 7–8). Деплоятся **C-2+C-3 вместе**:
> на сервере C-2 нет (`planner/` отсутствует — факт префлайта).

---

## 0. Scope

**Деплоим:**
- Код `main` → `/opt/diet_platform` (5 коммитов C-3 поверх C-2 `3d0c5c0`).
- Схему Phase 0: 4 таблицы + 3 колонки + 2 partial unique index — **идемпотентно через `init_db()`**, отдельная миграция не нужна (§19: «migration не нужна в строгом смысле»).
- Рестарт `diet-platform.service` + верификация.

**НЕ делаем (границы Phase 0):**
- Переключение/консолидация reminder-систем (ADR-4 — Phase 1).
- Re-enable Mini App (отдельная задача initData-валидации).
- Удаление legacy (`schedule.py`, `meal_scheduler.py`, мёртвые таблицы — §19/FM-12: ничего не удалять).
- Изменения `.env`, ключей, venv, systemd unit.
- Backfill — не нужен (§19: историй программ нет).

---

## 1. Precondition-проверки (§20-0)

| # | Проверка | Статус (read-only префлайт 2026-09-15) |
|---|---|---|
| 1.1 | SSH-доступность | ✅ работает по канону SERVER_ACCESS_WHIMCO.md: `timeout 40 ssh -o ControlMaster=no -o ControlPath=none -F /data/data/com.termux/files/home/.ssh/config whimco '...'` (алиас → 185.233.184.192, root, ключ id_ed25519_whimco); НЕ передавать cwd в tool-вызов |
| 1.2 | Сервис живой | ✅ `systemctl is-active diet-platform` = `active`; юнит подтверждён: WorkingDirectory=/opt/diet_platform, ExecStart=venv/bin/python main.py, User=root (ровно §2.1 архитектуры) |
| 1.3 | SQLite ≥ 3.45.1 | ✅ python3 sqlite_version = **3.45.1** (sqlite3 CLI на сервере не установлен — использовать python) |
| 1.4 | Partial unique indexes на **копии** прод-БД | ✅ закрыт при шаге C (репетиция): PROBE1/PROBE2 — `IntegrityError` на вторую active-программу/план |
| 1.5 | Чистота прод-каталога | ✅ git на сервере **отсутствует** (см. §3) — конфликтов pull не бывает; следы ручных правок: `bot.py.bak_r2`, `database_migration_v2.sql` (не трогаем, аддитивный overlay их не удаляет) |
| 1.6 | venv | ✅ `/opt/diet_platform/venv` существует (ExecStart использует); pip-freeze сверить при шаге C, если что-то упадёт по импортам |
| 1.7 | Прод-БД | ✅ `/opt/diet_platform/diet_platform.db`; WAL-сайдкаров в момент проверки нет — но копировать только backup API (§2.1) |

---

## 2. Backup [ШАГ A] — ✅ ВЫПОЛНЕН 2026-09-15

Обязателен до любого касания кода/БД (DoD: «Migration reversible»).

**Фактический прогон (whimco, root):**

| Действие | Факт |
|---|---|
| Место на диске | 24G свободно на `/` (59% занято) — достаточно |
| §2.1 БД (backup API через **python** — sqlite3 CLI на сервере отсутствует) | `/opt/diet_platform/backups/diet_platform_2026-09-15_pre_phase0.db` — 495616 bytes, онлайн-копия живой БД |
| §2.2 Код | `/opt/diet_platform/backups/code_pre_phase0_2026-09-15.tar.gz` — 101 запись, 174KB (exclude: venv, `__pycache__`, `*.pyc`, backups; `.env` включён в состав отката, остаётся на сервере) |
| §2.3 Верификация | `integrity_check` = **ok**; таблиц в копии = **15** (ожидание после Phase 0: 19); `user_profiles` = **2 записи** (совпадает с §19) |
| Контроль распаковки | test-extract в /tmp + `diff -r` против живого дерева (с теми же exclude) = **CLEAN** — тарболл полон и годен для отката |

Отчёт об отклонениях от плана: бэкап БД выполнен python-методом вместо sqlite3 CLI (CLI не установлен — адаптация по смыслу §2.1, backup API сохранён); тарболл снят с дополнительным exclude backups (иначе тарболл включал бы сам себя).

```bash
mkdir -p /opt/diet_platform/backups
# 2.1 Онлайн-копия через backup API (НЕ cp — прод-БД в WAL-режиме, живой сервис):
sqlite3 /opt/diet_platform/diet_platform.db \
  ".backup '/opt/diet_platform/backups/diet_platform_2026-09-15_pre_phase0.db'"
# 2.2 Файловый снапшот кода:
cd /opt && tar czf /opt/diet_platform/backups/code_pre_phase0_2026-09-15.tar.gz diet_platform \
  --exclude='diet_platform/venv' --exclude='diet_platform/__pycache__'
# 2.3 Верификация бэкапа:
sqlite3 /opt/diet_platform/backups/diet_platform_2026-09-15_pre_phase0.db \
  "PRAGMA integrity_check; SELECT COUNT(*) FROM sqlite_master WHERE type='table';"
```

Критерий: `integrity_check` = `ok`; счётчик таблиц = текущее кол-во + резерв под 4 новые.

**Точка отката кода:** состояние прода «до» = тарболл §2.2 (`code_pre_phase0_2026-09-15.tar.gz`); логическая точка в истории — коммит `3d0c5c0` (C-2), но на сервере git нет, откат — распаковкой тарболла (§7).

---

## 3. Доставка кода [ШАГ B] — ✅ ВЫПОЛНЕН 2026-09-15 — overlay через git archive (git на сервере НЕТ)

**Фактический прогон:**

| Действие | Факт |
|---|---|
| Архив | `git archive 9205cbf` → 117 записей, 262642 bytes; sanity: `planner/` ×7, tests ×11, **0 × .env, 0 × *.db/** — `.db-wal` снят с трекинга в C-2, в архив не попал |
| Дивергенция сервера vs 9205cbf | `bot.py`, `main.py` совпали бит-в-бит (сервер = baseline); различались ровно 4 изменённых коммитами файла — dry-run гейт предсказуем |
| scp + md5 | `/tmp/dp_9205cbf.tgz` на whimco, md5 `637722014a5b1fb17fdd6cdbc3110ae6` = локальному |
| **Dry-run гейт** (`tar dzf`) | 300 строк; содержательные различия (Size/Cannot-stat) = ровно файл-сет C-2+C-3 из `git diff afe2d90..9205cbf` + `TEAM_NOTES.md`; остальное косметика (Mode/Uid/Gid/Mod time) |
| Распаковка | `tar xzf --exclude=.env.bak-20260630181938 --no-same-owner -C /opt/diet_platform` → **OVERLAY-OK** |
| Верификация md5 | 6 ключевых файлов + `TEAM_NOTES.md` = бит-в-бит `9205cbf`; реальный `.env` не тронут; прод-БД не тронута (495616 bytes, mtime 13:09) |
| Smoke | `compileall` OK (planner/bot_handlers/modules/building_blocks/api/main/bot/database); `import planner` OK; `miniapp_enabled = False`; таблиц в БД = 15 (Phase 0 ещё нет — до шага C); сервис **не перезапускался**: старый процесс PID 764704 с 2026-09-12 продолжает работать старым кодом из памяти |

**Отклонения/находки:**
1. `--exclude=.env.bak-20260630181938` — трекаемый в репо env-бэкап содержит **2 реальных Gemini-ключа**; по духу §3 («.env не затрагивается») исключён из распаковки; на сервере файл отсутствовал и **не создан**. 🚩 Находка вне деплоя: секреты в git-истории → отдельная задача (ротация ключей + чистка истории).
2. `--no-same-owner` — распаковка под root иначе выставила бы uid из архива.
3. `TEAM_NOTES.md` на сервере разошёлся с репо (сервер `a046…` ≠ репо `704d…`) — перезаписан версией репо; прежняя копия сохранена в step-A тарболле (наличие проверено).

**Факт префлайта:** `/opt/diet_platform` — не git-репозиторий (`NO-GIT`); прежние деплои
делались копированием файлов. Поэтому git pull/push **не используется вовсе** —
это снимает и PAT-вопрос из шага B, и риск 6 из §8.

Механика: ровно трекаемые файлы локального `main` (9205cbf) поверх прод-каталога;
`.env`, БД, логи, `bot.py.bak_r2` и прочий untracked прод-контент не затрагиваются:

```bash
# Локально (телефон), из корня diet_platform:
cd projects_17/diet_platform
tar czf /tmp/dp_9205cbf.tgz .gitignore -C . . 2>/dev/null  # см. уточнение ниже
```

Рабочая однострочника (без промежуточного файла, трекаемое дерево 9205cbf):

```bash
cd projects_17/diet_platform
git archive --format=tar.gz -o /tmp/dp_9205cbf.tgz 9205cbf
timeout 120 scp -F /data/data/com.termux/files/home/.ssh/config /tmp/dp_9205cbf.tgz \
  whimco:/tmp/dp_9205cbf.tgz
# На whimco — сначала DRY-RUN (посмотреть, что перезапишется):
timeout 60 ssh -o ControlMaster=no -o ControlPath=none -F /data/data/com.termux/files/home/.ssh/config whimco \
  'tar tzf /tmp/dp_9205cbf.tgz | head -30; tar dzf /tmp/dp_9205cbf.tgz -C /opt/diet_platform 2>&1 | head -20'
# Реальное распаковывание (только после бэкапа §2 иdry-run без сюрпризов):
timeout 60 ssh -o ControlMaster=no -o ControlPath=none -F /data/data/com.termux/files/home/.ssh/config whimco \
  'tar xzf /tmp/dp_9205cbf.tgz -C /opt/diet_platform && ls -d /opt/diet_platform/planner && echo OVERLAY-OK'
```

`git archive` кладёт в архив `planner/ ×7, database.py, tests/, bot_handlers/, modules/,
building_blocks/…` — всё состояние main, включая C-2. Откат кода — не git checkout,
а распаковка тарболла из §2.2 (кодовое состояние «до»). Отдельно: **Rollback code
[ШАГ B-откат]** — `tar xzf /opt/diet_platform/backups/code_pre_phase0_2026-09-15.tar.gz
-C /opt` восстанавливает прежнее дерево (тарболл снят с `--exclude` venv/pycache,
поэтому поверх живого каталога восстанавливает именно файлы кода).

---

## 4. Migration (идемпотентная) [ШАГ C] — ✅ ВЫПОЛНЕН 2026-09-15

**Фактический прогон (в три фазы — репетиция → прод → идемпотентность):**

| Фаза | Факт |
|---|---|
| Репетиция на копии бэкапа (`/tmp/dp_rehearsal.db`) | init_db OK: 15→19 таблиц, оба partial unique index созданы, 3 колонки добавлены; пробы §1.4 **PROBE1-OK / PROBE2-OK** (`IntegrityError` на вторую active-программу и второй active-план) → прекондишн 1.4 закрыт |
| Снимок «before» прода | 15 таблиц; 41 колонка user_profiles (runtime-ALTER'ы на месте); counts: user_profiles=2, recipe_sessions=0, shopping_lists=0 |
| **Прод-миграция** (`init_db()` через venv-python) | `MIGRATION-DONE`; **integrity=ok**, 19 таблиц, 4 Phase 0-таблицы на месте, оба unique-инварианта созданы, колонки: `restrictions TEXT`, `activity TEXT`, `timezone TEXT DEFAULT 'Europe/Moscow'` — ровно §13; users=2 целы, events пуста (0) |
| Идемпотентность | повторный init_db() на проде — no-op: 19 таблиц, integrity=ok → рестарт службы не добавит ничего неожиданного |

Примечание: миграция выполнена при живом старом сервисе (PID 764704) — DDL аддитивный
(IF NOT EXISTS / exception-pass), WAL выдерживает короткую конкуренцию за write-lock
(timeout=30 в aiosqlite); никаких наблюдаемых конфликтов не возникло.

`init_db()` создаёт всё сам при старте, но прогоняем **до** рестарта, чтобы failure
был видим вне боевого перезапуска:

```bash
cd /opt/diet_platform && venv/bin/python - <<'EOF'
import asyncio, database
asyncio.run(database.init_db())
print("schema OK:", database.DB_PATH)
EOF
```

Скрипт идемпотентен: `CREATE TABLE IF NOT EXISTS`, ALTER'ы с exception-pass
(паттерн §19). Runtime-колонки (`puhlyash_*` и др.) на проде уже существуют —
хендлеры их создали live-ALTER'ами ранее.

Проверка после:

```bash
sqlite3 /opt/diet_platform/diet_platform.db \
  "SELECT name FROM sqlite_master WHERE type='table' AND name IN
   ('diet_programs','weekly_plans','meal_state','events');
   PRAGMA table_info(user_profiles);" | grep -E "restrictions|activity|timezone"
# Ожидаем: 4 таблицы + 3 колонки. Индексы:
sqlite3 /opt/diet_platform/diet_platform.db \
  "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_one_active%';"
```

---

## 5. Рестарт [ШАГ D] — ✅ ВЫПОЛНЕН 2026-09-15 20:57 UTC — с учётом известной хрупкости

**Фактический прогон:**

| Действие | Факт |
|---|---|
| Снимок до рестарта | старый PID **764704** (запущен 2026-09-12 06:52, работал по старому коду из памяти) |
| Очистка `__pycache__` (§5, TEAM_NOTES) | выполнена по всему дереву |
| `systemctl restart` | SSH-вызов упёрся в 90s timeout — **ожидаемо**: юнит висел в `stop-sigterm` до TimeoutStopSec |
| Зомби-хрупкость | подтверждена журналом: `State 'stop-sigterm' timed out. Killing.` → `Killing process 764704 with signal SIGKILL` → `Failed with result 'timeout'` → `Started diet-platform.service`. **Ручной kill -9 не понадобился** — systemd завершил сам |
| Новый процесс | PID **1715032**, старт 20:57:52 UTC, `active/running`, стабилен |
| Журнал старта | без Traceback; ключевые строки нового кода: `🚫 Mini App routes disabled (miniapp_enabled=false, Phase 0)`, `LLMFactory (gemini-3.1-flash-lite, KeyPool 14 ключей)`, `Database initialized`, `Scheduler started, jobs loaded`, `Application startup complete` |
| `/health` | `{"status":"ok","service":"diet-platform","version":"1.0.0"}` |

**Урок для TEAM_NOTES (Phase 1, вне этого деплоя):** SIGTERM игнорируется обработчиками —
каждый рестарт занимает TimeoutStopSec и проходит через SIGKILL; рассмотреть явный
graceful-shutdown / TimeoutStopSec в юните.

```bash
cd /opt/diet_platform
find . -name '__pycache__' -exec rm -rf {} +          # ОБЯЗАТЕЛЬНО (TEAM_NOTES)
systemctl restart diet-platform
# Хрупкость: SIGTERM иногда не убивает процесс (зомби 'sleeping', systemd
# считает сервис active, новый start ничего не делает). Проверяем возраст процесса:
PID=$(systemctl show diet-platform -p MainPID --value)
ps -o pid,lstart,cmd -p "$PID"
# Если процесс старый (не перезапустился):
#   kill -9 "$PID"   # systemd поднимет сам (Restart=always)
```

---

## 6. Post-deploy verification [ШАГ E] — чеклист §20-9

| # | Проверка | Команда/действие | Критерий |
|---|---|---|---|
| 6.1 | Сервис | `systemctl is-active diet-platform` | ✅ active, PID 1715032, uptime 3ч+ |
| 6.2 | Health API | `curl -s http://localhost:8150/health` | ✅ `{"status":"ok"}` |
| 6.3 | Журнал старта | `journalctl -u diet-platform --since 20:57:50` | ✅ 0 Traceback; `Database initialized`; Vault-упоминаний нет — fail-soft отработал молча |
| 6.4 | Бот отвечает | `/start` реальным ботом | ⬜ owner: транспорт поднят (`Telegram bot enabled`); живая проверка — за владельцем |
| 6.5 | **E2E на whimco** | `cd /opt/diet_platform && venv/bin/python tests/e2e_diet_picker.py --fast` | ✅ **УЖЕ ВЫПОЛНЕН ДО РЕСТАРТА 2026-09-15: PASS, exit 0** — полный флоу 11 исходящих (старт→кабинет→опросник→карточки→план), все §20-8 инварианты зелёные, WebApp-ссылка исчезла; temp-БД изолирована, прод не тронут. После рестарта — контрольный повтор |
| 6.6 | Существующие пользователи | кабинет + напоминания одним из 2 реальных пользователей | ⬜ owner: данные целы (users=2, meal_schedule=5, scheduler jobs loaded); живая проверка кабинета/напоминаний — за владельцем |
| 6.7 | Память жива | после первого «Подбирай!» реального флоу: `SELECT * FROM events ORDER BY ts DESC LIMIT 5` | ⬜ owner: events пуста (0) до первого реального флоу — механика подтверждена E2E |
| 6.8 | PII-аудит | `journalctl` + `logs/diet_platform.log` | ✅ свежий лог с рестарта: 0 × health_notes/«Здоров», 0 × текстов сообщений |
| 6.9 | Irisochka smoke | реальный quick-tip в боте | ✅ LLMFactory-путь подтверждён E2E с LLM (карточки+план на реальных ключах; KeyPool gemini+groq загружен); точечный quick-tip в боте — за владельцем |
| 6.10 | (Опция) полный E2E с LLM | `tests/e2e_diet_picker.py` без `--fast` | ✅ ВЫПОЛНЕН: PASS за 6.6s — карточки 2.6s / план 3.9s на реальном Gemini |

DoD после шага 9: whimco-пункты §23 закрыты прогоном 2026-09-15/16 (6.1–6.3, 6.5, 6.8–6.10);
owner-остаток — только живые Telegram-действия (6.4, 6.6-проверка, 6.7 после первого реального флоу).
Наблюдение вне деплоя: core-KeyPool грузит 3+3 ключа (gemini+groq), leviathan-пул — 14; вызовы LLM прошли — сверить при ротации ключей.

---

## 7. Rollback

| Слой | Команда |
|---|---|
| Код | `cd /opt/diet_platform && git checkout 3d0c5c0 && find . -name '__pycache__' -exec rm -rf {} + && systemctl restart diet-platform` (по механике §5) |
| БД (мягкий) | новые таблицы безвредны: `DROP TABLE IF EXISTS meal_state, events, weekly_plans, diet_programs;` — 3 колонки `user_profiles` можно оставить |
| БД (полный, сервис ОСТАНОВЛЕН) | `systemctl stop diet-platform && sqlite3 /opt/diet_platform/diet_platform.db ".restore '/opt/diet_platform/backups/diet_platform_2026-09-15_pre_phase0.db'" && systemctl start diet-platform` |
| Verify отката | `/health` ok; бот отвечает;reminder-fallback жив |

---

## 8. Risks (реальные, из фактов)

1. **Restart-зомби** (TEAM_NOTES, наблюдавшийся случай) — mitigation в §5 (проверка возраста процесса, kill -9).
2. ~~Локальные правки на сервере~~ → замещено фактом 1.5: git нет, overlay аддитивен; но **dry-run в §3 обязателен** — если tar -d покажет неожиданные конфликты, остановиться.
3. **Прод-БД в WAL** — только backup API, никаких `cp` на живом файле (в момент проверки сайдкаров не было, но сервис мог ещё не чекпоинтить).
4. **Vault** — ❗ попр��вка факта (E2E-прогон 2026-09-15): `vault_client_v2` отсутствует **и на сервере** (не только локально); живой прод-сервис работает с этим fail-soft прямо сейчас, E2E-харнесс воспроизвёл то же состояние успешно. Ожидать после рестарта: тот же лог «Vault secrets load failed» (fail-soft, не fatal). Регрессом будет только если он станет фатальным.
5. ~~SSH с телефона~~ → снято: работает по канону SERVER_ACCESS_WHIMCO.md (обязательные флаги: timeout + ControlMaster=no + -F; правило «без cwd в tool-вызове»).
6. ~~PAT в git remote~~ → снято: git-доставка исключена (§3); PAT-вопрос остаётся стоять отдельно вне этого деплоя.
7. **Irisochka теперь async через LLMFactory** — на сервере фабрика и ключи есть; smoke 6.9 закрывает.
8. **Впервые деплоятся C-2 и C-3 вместе** (на сервере нет planner/ и новой схемы) — объём схемы +4T +3C +2 idx применяется одним идемпотентным прогоном §4; откат — §7.

---

## 9. Порядок авторизации

Каждый шаг — отдельное явное OK владельца:

**[A] Backup → [B] Код (overlay, dry-run сначала) → [C] Schema → [D] Restart → [E] Verify** — ✅ ВСЕ ПЯТЬ ШАГОВ ВЫПОЛНЕНЫ 2026-09-15/16

Полный E2E с LLM (6.10) выполнен в рамках шага E: PASS за 6.6s, расход ≈ один реальный подбор. git push не требуется (§3).
Rollback (§7) остаётся доступным без изменений: код-тарболл + `.restore` бэкапа.
