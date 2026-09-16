# 🔐 TASK: Ротация скомпрометированных секретов + чистка git-истории

> Дата: 2026-09-16 · Статус: **ЗАДАЧА — НИЧЕГО НЕ ВЫПОЛНЕНО**
> Источник находки: шаг B деплоя §20-9 (dry-run гейт) + последующий аудит 2026-09-16.
> Все факты ниже проверены командами, не со слов. Отпечатки секретов маскированы намеренно.

---

## 1. Факты утечки (верифицировано 2026-09-16)

### 1.1 Трекаемый файл с секретами — на HEAD, не только в истории

```
git ls-files | grep -i "\.env"   →  .env.bak-20260630181938  ← ТРЕКАЕТСЯ СЕЙЧАС
```

- Попал в репо первым коммитом: **`15c35be` «Auto-sync: maintenance update» (2026-07-01)**.
- `.gitignore` содержит `.env` (строка 4), но **не** `.env.bak*` — файл прошёл мимо игнора.
- История файла: ровно один коммит (`15c35be`), дальше не менялся.

### 1.2 Секреты уже на GitHub

```
git ls-remote origin main  →  15c35be3f9404b6677223359f8adaf827ee08b58
```

`origin/main` стоит **ровно на утёкшем коммите** → файл с секретами физически лежит на
`github.com/lidenal85-blip/diet_platform`. Считать скомпрометированным независимо от
приватности репо.

> **Верификация 2026-09-16 (обостряет приоритет):** репо **ПУБЛИЧНЫЙ** — анонимный
> `GET api.github.com/repos/lidenal85-blip/diet_platform` → HTTP 200; файл с секретами
> скачивается кем угодно с tip of main без аутентификации. Экспозиция с 2026-07-01
> (~2,5 мес). Старый токен бота всё ещё жив → не угнан, но окно открыто.
> **Немедленная митигация:** перевести репо в Private (Settings → Danger Zone) до R1–R6.

### 1.3 Что именно утекло (из `.env.bak-20260630181938`)

| Секрет | Кол-во | Отпечатки (маскировано) | Статус |
|---|---|---|---|
| `GEMINI_API_KEY` | 1 | `AIzaSyAJ...If9M` | 🔴 утёк |
| `GEMINI_KEYS` | 8 | `AIzaSyB4...AeT4`, `AIzaSyCk...r1o8`, `AIzaSyB8...chOE`, `AIzaSyDo...ydaw`, `AIzaSyAZ...7l8U`, `AIzaSyDy...aW9M`, `AIzaSyBg...lm3Q`, `AIzaSyAo...Ebw8` | 🔴 утекли |
| `TELEGRAM_BOT_TOKEN` | 1 | md5: `00f93beab1` (46) | 🔴 **СОВПАДАЕТ С ПРОДОМ** |
| `USERBOT_RELAY_TOKEN` | 1 | md5: `7e1aaa207f` (43) | 🔴 прод-значение не проверялось → считать утёкшим |

**Итого 9 ключей Gemini + токен продового бота + relay-токен.**

### 1.4 Blast radius: прод-пул НЕ задет ротацией Gemini

Прод `.env` (whimco, fingerprint-проверка 2026-09-16): пул = **1 ключ** `AIzaSyB5...omeQ`
(+2 не-Gemini записи len=53, вероятно `gsk_` Groq). **Ни один из 9 утёкших ключей в
прод-пул не входит** → ротация утёкших Gemini-ключей не требует трогать прод-конфиг.

Но `TELEGRAM_BOT_TOKEN` продовый утёк **целиком** → бот может быть перехвачен кем угодно.

### 1.5 Бонус-утечка: GitHub PAT в remote URL

```
git remote -v  →  https://lidenal85-blip:ghp_***@github.com/...
```

PAT вшит в `.git/config` открытым текстом (и засветился в выводе сессии 2026-09-16).
Тоже подлежит ротации.

---

## 2. План ротации (порядок важен)

### Шаг R1 — немедленно: TELEGRAM_BOT_TOKEN (единственный активно-опасный)

1. @BotFather → `/mybots` → бот «Пухляш» → API Token → **Revoke** → новый токен.
2. Обновить `TELEGRAM_BOT_TOKEN` в `/opt/diet_platform/.env` на whimco.
3. Рестарт `diet-platform.service` (см. §5 — зомби-хрупкость).
4. Проверка: `/health` ok, бот отвечает на `/start`, в логе 0 Traceback.
5. Проверить, что старый токен больше не отвечает: `curl https://api.telegram.org/bot<СТАРЫЙ>/getMe` → 401.

 downtime ≈ 1 рестарт; новое сообщение пользователей при revocation прерывается только на время рестарта.

> **Статус 2026-09-16: ВЫПОЛНЕНО (07:00 UTC).** Токен установлен на прод через stdin
> (md5 `25c4e5c117`), рестарт чистый, health ok. Telegram-пробы: **OLD → 401** на все
> методы; NEW: username/first_name/getMyName/description аутентичны, webhook пуст.
> Репо переведён владельцем в **Private**. Локальный `.env` обновлён. Wizard удалён
> (интерактивный ввод больше не нужен). Детальный аудит: `SECURITY_AUDIT_2026-09-16.md`.

### Шаг R2 — USERBOT_RELAY_TOKEN: реверифицировано 2026-09-16 — подсистема МЕРТВА, ротация НЕ нужна

Факты (whimco, read-only): процессов и systemd-юнитов relay нет; `/opt/den4ik-claude/userbot_relay.py`
и `/opt/telegram-agent-book/my_account.session` не существуют; код только **читает** переменную
(`config.py:98` → поле `userbot_relay_token:25`, `vault_integration.py:83`), ни один consumer
её не использует; `modules/notifier/sender.py` работает на собственном `TELEGRAM_BOT_TOKEN`
(CONFLICT-01 закрыт 2026-06-30); ни один тест на токен не ссылается.

Утёкшее значение не даёт доступа ни к чему — релея не существует. Ротировать нечего;
утёкшая строка уходит из истории вместе с R6.

**Owner decision (одно слово):**
- **A (рекомендуется):** убрать `USERBOT_RELAY_TOKEN` из прод `.env`; кодовое поле
  (config.py:25 + маппинг :98) и элемент списка vault_integration.py:83 удалить
  отдельным минимальным коммитом.
- **B:** оставить как legacy — на безопасность после R6 не влияет.

### Шаг R3 — ротация 9 утёкших Gemini-ключей (zero-impact на прод)

> **Статус 2026-09-16: ВЫПОЛНЕНО И ВЕРИФИЦИРОВАНО.** Ключи удалены владельцем в AI Studio.
> Контрольный E2E с реальным LLM на whimco: **PASS exit 0** — карточки 2.9s, план 4.5s
> (реальные вызовы API), KeyPool загрузился, прод-пул `AIzaSyB5...omeQ` жив.
> §20-8 инварианты целы. Прод-конфиг не менялся.
1. AI Studio → удалить все 9 ключей (отпечатки в §1.3 для сверки).
2. Выпустить замену только если где-то вне прода ещё используются (локальные дев-среды —
   владелец знает). Прод-пул не трогать: его ключ не из утёкших.
3. Сверка после: отпечаток прод-ключа на whimco остался `AIzaSyB5...omeQ`, E2E с LLM зелёный.

### Шаг R4 — GitHub PAT

1. GitHub → Settings → Developer settings → PAT → **Revoke** `ghp_Ito9...`.
2. Выпустить новый (fine-grained, только diet_platform, только contents).
3. Убрать PAT из remote URL: `git remote set-url origin https://github.com/lidenal85-blip/diet_platform.git`
   + credential helper (`git config credential.helper store` — с осознанием того же риска,
   лучше SSH-ключ).

### Шаг R5 — чистка рабочего дерева (до переписывания истории)

```bash
git rm --cached .env.bak-20260630181938
printf "\n# env-семейство целиком (бэкапы .env тоже секреты)\n.env.*\n*.env.bak*\n" >> .gitignore
git add .gitignore && git commit -m "chore(security): untrack .env.bak, ignore env backups"
```

Дополнительно (обязательная сверка перед R6): `git ls-files | grep -iE "env|secret|token|key|\.bak"`
— убедиться, что других трекаемых секретоносцев нет (`.env.example` — плейсхолдеры, ок).

### Шаг R6 — чистка git-истории (переписывание)

> **Статус 2026-09-16: ЗАВЕРШЕНО ПОЛНОСТЬЮ.** Рерайт (23 коммита, HEAD `0fb4d59`) →
> гейты чистые → force-push выполнен через новый PAT (`15c35be…759a1e3 forced update`),
> **remote tip = local HEAD (`759a1e3`) — PUSH-VERIFIED**; файла на remote больше нет
> (GET contents → 404). gh CLI ре-авторизован тем же PAT — helper для будущих push
> починен. Локальный `.git` почищен `gc --prune=now` (объект `15c35be` удалён).
> Осталось: GitHub Support на GC unreachable-объектов (необязательно: все секреты
> уже мертвы). Бэкап пре-рерайта: `/tmp/dp_history_pre_r6.bundle` (⚠️ в /tmp).
>
> 1. **Бэкап-точка отката:** `/tmp/dp_history_pre_r6.bundle` (полная история до
>    рерайта, verify OK; ⚠️ лежит в /tmp телефона — сохранить до перезагрузки).
> 2. **Рерайт:** `git filter-repo --invert-paths --path .env.bak-20260630181938 --force`
>    — 23 коммита переписаны, HEAD `0fb4d59`, origin снят (штатно) и пере-добавлен
>    чистым URL (без вшитого PAT).
> 3. **Гейты:** файл отсутствует во всех деревьях (`--all`, diff-filter=A — none);
>    уточнённый скан реальных секрет-форматов по полной истории — **0 вхождений**
>    (широкий первый гейт давал 9 ложных: имена переменных в удалённом wizard'е
>    и маскированные отпечатки из security-доков); `git fsck --full` чистый;
>    рабочее дерево чистое; локальный `.env.bak` остался на диске untracked+ignored.
> 4. **Блокер push:** ВСЕ старые PAT мертвы (вшитый в remote, оба в
>    `~/.git-credentials`, токен gh CLI — «Invalid username or token»; SSH-ключа
>    для GitHub нет) → финальный push выполняет владелец.
>
> **Ручной шаг владельца (после создания нового PAT в Settings → Developer
> settings → PAT, доступ к lidenal85-blip/diet_platform):**
>
> ```bash
> cd /storage/emulated/0/PROJECTS/workstation/freebuff/projects_17/diet_platform
> git push --force origin main
> git ls-remote origin main   # хэш должен совпасть с git rev-parse HEAD (0fb4d59…)
> ```
>
> После подтверждения: GitHub Support на GC unreachable-объектов; R6 закрыт.

```bash
pip install git-filter-repo   # или pipx
git filter-repo --invert-paths --path .env.bak-20260630181938 --force
# гейт:
git log --all --oneline -- .env.bak-20260630181938        # → пусто
git show 15c35be --stat | grep env.bak                     # → пусто
# затем пере-добавить origin (filter-repo его сносит) и force-push:
git remote add origin https://github.com/lidenal85-blip/diet_platform.git
git push --force origin main
```

⚠️ После force-push GitHub может ещё держать объекты в кэше (unreachable) — см. §4 риски.
Альтернатива при нежелании переписывать: удалить репо и recreate (жёстче, но проще).

---

## 3. DoD (Definition of Done)

- [x] R1: **прод** переведён на новый токен (проверено серверно: md5 в проде ≠ `00f93beab1`, бэкап `.bak-rot-*` существует, рестарт после прогона, бот отвечает на /start). Локальный дев-`.env` обновить отдельно.
- [x] R1+: репо переведён в Private владельцем 2026-09-16; OLD токен 401; идентичность/webhook аутентичны (см. SECURITY_AUDIT §1)
- [ ] R2: владелец выбрал A (удалить мёртвую переменную из прода + минимальный кодовый коммит) **или** B (оставить legacy; после R6 не влияет на безопасность).
- [x] R3: 9 утёкших Gemini-ключей удалены в AI Studio владельцем; прод-пул не тронут (`AIzaSyB5...omeQ`), E2E с LLM на whimco PASS exit 0.
- [ ] Прод-бот работает на новом токене; `/health` ok; E2E на whimco зелёный.
- [ ] `.env.bak-20260630181938` не трекается; `.gitignore` покрывает env-бэкапы.
- [x] `git log --all -- .env.bak-20260630181938` пуст; origin/main переписан force-push-ом (PUSH-VERIFIED: remote tip = `759a1e3`; файл на remote → 404).
- [ ] Прод-пул Gemini не изменился (`AIzaSyB5...omeQ`), E2E с LLM на сервере PASS.
- [ ] `git ls-files` не содержит ни одного файла с реальными секретами.
- [ ] TEAM_NOTES.md дополнен уроком: env-файлы (включая *.bak) никогда не коммитятся.

## 4. Риски (все закрыты 2026-09-16)

| Риск | Статус |
|---|---|
| Force-push ломает чужие клоны | ✅ Клонов нет (сервер не git-клон); push выполнен, verified |
| GitHub кэширует unreachable-объекты | 🟡 Технически остаётся до GC; **не опасно**: все секреты уже мертвы (R1/R3/R4) — Support-запрос опционален |
| Рестарт бота при R1 упрётся в SIGTERM | ✅ Прошёл чисто (RC=0, без зомби-этапа) |
| Relay-механика сломается после R2 | ✅ Снят реверификацией: подсистема мертва (нет процессов/юнитов/файлов/consumers) |
| PAT в credential store повторит уязвимость | 🟡 Новый PAT в `~/.git-credentials` + gh hosts.yml — тот же класс хранения; ротация при следующем инциденте; SSH-ключ для GitHub — кандидат на Phase 1 |
| 🆕 gh CLI credential helper перебивает store | ✅ Найден и устранён: gh ре-авторизован тем же PAT (helper больше не подсовывает мёртвый токен) |

| Риск | Митигация |
|---|---|
| Force-push ломает чужие клоны | Клонов кроме локального нет (сервер без git); подтверждено при деплое §20-9 |
| GitHub кэширует unreachable-объекты | После force-push: Support request на GC / или recreate-репо; секреты к тому моменту уже ротированы — история больше не опасна |
| Рестарт бота при R1 упрётся в SIGTERM | Известная хрупкость: ждать TimeoutStopSec → systemd SIGKILL сам; не паниковать, дождаться нового PID (задокументировано в DEPLOY_PLAN §8) |
| Relay-механика сломается после R2 | Риск снят реверификацией 2026-09-16: подсистема мертва (нет процессов/юнитов/файлов, нет consumers) — удалять нечего, ломаться нечему |
| PAT в credential store повторит уязвимость | Предпочесть SSH-ключ для origin |

## 5. Откаты

- Ротация токенов не откатывается по определению (revoked). Откат возможен только
  «назад к старому токену» **до** revoke в BotFather — поэтому менять прод `.env`
  синхронно с выпуском нового, revoke — последним.
- История: точка до `git filter-repo` = backup `git bundle create /tmp/dp_history.bundle --all`.
