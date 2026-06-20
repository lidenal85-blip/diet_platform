# 🧁 Паспорт проекта: Diet Platform «Пухляш»

> Последнее обновление: **2026-06-19**

---

## Основные данные

| Параметр | Значение |
|---|---|
| **Название** | Diet Platform «Пухляш» |
| **Сервер** | `leviathanstory.ru` (`78.17.24.96`) |
| **Путь** | `/opt/diet_platform` |
| **API-порт** | `8150` |
| **Сервис** | `diet-platform.service` |
| **База данных** | `/opt/diet_platform/diet_platform.db` (SQLite, WAL) |
| **Gemini-модель** | `gemini-3.1-flash-lite` (K1-K14 ротация) |
| **Telegram-бот** | `@Fatboyandgirl_bot` (token в `.env`) |
| **Mini App** | `https://leviathanstory.ru/diet/app` |
| **Питон** | `/usr/bin/python3` (системный, venv удалены) |
| **Userbot** | `/opt/telegram-agent-book/my_account.session` (Pyrogram) |

---

## Маскот Пухляш

**Образ:** Рыжий кот в фартуке + мышка-помощник
**Персонаж:** Свой парень, любит поесть, знает толк в обычной еде с нотками эксклюзивности
**Тон:** Дружелюбный, чуть юмор, но со знанием дела
**Таглайн:** «Свой парень, знает толк в еде!»
**Фишка:** Бот проверяет совместимость ингредиентов (не даст дать смешать селёдку с молоком)
**Изображения:** `/opt/diet_platform/assets/mascot/` (добавить)

---

## Архитектура (2026-06-19)

```
[Telegram Bot @Fatboyandgirl_bot]
        ↓ aiogram3 + FSM
[FastAPI :8150]
        ↓
├── Рецепты  → modules/recipes/engine.py → Gemini 3.1-flash-lite
├── Пухляш  → modules/puhlyash/persona.py → настроение + рецепт без бюджета
├── Диеты   → modules/diet_registry/ → SQLite
├── Уведом.  → modules/notifier/sender.py → Pyrogram userbot
├── Распис. → modules/scheduler/meal_scheduler.py → APScheduler
├── Реакции → modules/reactions/engine.py → SQLite
├── Фитнес  → modules/fitness/engine.py → Gemini
└── Mini App → api/miniapp_router.py → https://leviathanstory.ru/diet/app
```

---

## Бот-хендлеры

| Файл | Назначение | Статус |
|---|---|---|
| `bot.py` | Главный бот + запуск | ✅ |
| `bot_handlers/recipes.py` | Рецепты, холодильник, бюджет, шеф, Пухляш | ✅ |
| `bot_handlers/puhlyash_settings.py` | Настройка маскота + тест уведомлений | ✅ |
| `bot_handlers/reactions.py` | Лайк/дизлайк/сохранить/альтернативы/мастер | ✅ |
| `bot_handlers/meal_schedule_v2.py` | Расписание питания v2 (все приёмы) | ✅ |
| `bot_handlers/diet_picker.py` | Подбор диеты (опросник + 3 варианта) | ✅ |
| `bot_handlers/cabinet.py` | Личный кабинет (FSM) | ✅ |
| `bot_handlers/schedule.py` | Старое расписание (fallback) | ⚠️ устаревшее |

---

## Модули

| Модуль | Назначение | Статус |
|---|---|---|
| `modules/puhlyash/persona.py` | Персонаж, настроения, промпты (без бюджета!) | ✅ |
| `modules/recipes/engine.py` | Генерация рецептов (Gemini) | ✅ |
| `modules/recipes/prompt_builder.py` | Промпты с учётом профиля | ✅ |
| `modules/reactions/engine.py` | Реакции, inline-кнопки | ✅ |
| `modules/fitness/engine.py` | Упражнения без снарядов (Gemini) | ✅ |
| `modules/notifier/sender.py` | Pyrogram userbot + авто-реконнект | ✅ |
| `modules/scheduler/meal_scheduler.py` | APScheduler, CronTrigger, Europe/Moscow | ✅ |
| `api/miniapp_router.py` | Telegram Mini App + профиль API | ✅ |
| `api/cabinet_router.py` | HTML-кабинет (дублирует Mini App) | ⚠️ можно удалить |

---

## База данных (sqlite)

| Таблица | Назначение | Строк |
|---|---|---|
| `recipes` | Генерированные рецепты | 28 |
| `diet_master` | Верифицированные диеты | 12 |
| `user_profiles` | Профили пользователей | 2 |
| `meal_schedule` | Приёмы пищи | 5 |
| `reactions` | Лайки/дизлайки/сохранённые | 0 |
| `diary_entries` | Дневник (запланирован, не реализован) | 0 |
| `dlq` | Ошибки pipeline | 137 |

---

## Функциональность бота

### Реализовано ✅

| Кнопка | Описание |
|---|---|
| 🎯 Подобрать диету | Опросник 4 шага → Gemini даёт 3 варианта → план на неделю |
| 👤 Кабинет | Уровень/эксп., бюджет, время, исключения, рецепт дня |
| 🍝 Рецепт от Пухляша | Случайный рецепт с настроением, без бюджетных ограничений |
| 👨‍🍳 Рецепты | 4 режима: быстро/дом/ресторан/ПП, учитывает профиль |
| 🧊 Холодильник | Рецепт из перечня продуктов |
| 💰 По бюджету | Ужин на сумму |
| 👨‍🍳 Шеф на телефоне | Чат с Gemini в роли шефа |
| ⏰ Расписание | Приёмы пищи с именами, вкл/выкл, стандартное |
| 🍝 Пухляш | Настройка маскота + тест уведомлений |
| 👍/👎 inline | Реакции на рецепты + причина |
| 🔄 Альтернативы | 2 варианта альтернативного рецепта |
| 💡 Мастер эксперим. | Диалог с Пухляшем, проверка совместимости |
| 📱 Mini App | Telegram WebApp с двумя вкладками |

### Запланировано 🔧

| Функция | Приоритет |
|---|---|
| 👍/👎 Тестирование реакций (нет данных) | П1 |
| 🔔 Уведомления в личку (тест по кнопке в Пухляш) | П1 |
| 🕊️⃣ Цены на продукты в рецепте | П2 |
| 📰 Дневник пользователя | П2 |
| 🧠 RAG-анализ привычек (ChromaDB) | П2 |
| 🛒 Интеграция с магазинами/ценами | П3 |
| 💳 Монетизация (подписка) | П3 |

---

## Настройка nginx

```nginx
location ^~ /diet/ {
    proxy_pass http://127.0.0.1:8150/diet/;
}
```
Mini App: `https://leviathanstory.ru/diet/app?uid={tg_id}`

---

## Команды для сессии

```bash
# Перезапустить
fuser -k 8150/tcp 2>/dev/null; sleep 2 && systemctl start diet-platform

# Логи
systemctl status diet-platform
journalctl -u diet-platform -n 30 --no-pager
cat /opt/diet_platform/logs/diet_platform.log | tail -30

# Проверка синтаксиса
cd /opt/diet_platform && python3 -c "import bot; print('ok')"

# БД
curl -s http://localhost:8150/health

# Тест Gemini
python3 -c "from modules.puhlyash.persona import generate_puhlyash_recipe; import asyncio; r=asyncio.run(generate_puhlyash_recipe()); print(r['title'])"
```

---

## Известные проблемы

| Проблема | Статус |
|---|---|
| Pyrogram-сессия занята `den4ik-claude.service` | Решено: авто-реконнект в sender.py |
| `meal_breakfast='01:04'` (баг FSM) | Исправлено, сброшено |
| DLQ 137 записей | Ошибки старого pipeline поиска, не критично |
| `schedule.py` - устаревшее | Заменить на `meal_schedule_v2.py` |
| `api/cabinet_router.py` - дублирует Mini App | Можно удалить |

---

## Роадмап v4 — Личный AI-ассистент

Подробно: `/opt/diet_platform/start_here/ROADMAP_v4_assistant.md`

Коротко:
1. `modules/diary/` — дневник (текст + голос)
2. `modules/rag/` — ChromaDB (port 8009 уже есть)
3. `modules/planner/` — 3 варианта плана недели
4. FastAPI endpoint + HTML страница выбора
5. Уведомления по расписанию, покупкам, воде

---

## Структура профиля пользователя (user_profiles)

Основные: `cook_level`, `experiment_level`, `budget_level`, `max_cook_time`, `excluded_foods`
Расписание: `meal_breakfast/lunch/dinner`, `recipe_day_time`, `recipe_day_enabled`
Уведомления: `notify_personal`, `notify_meals`, `notify_recipe_day`
Пухляш: `puhlyash_name`, `puhlyash_specialty`, `puhlyash_tone`, `puhlyash_catchphrase`, `puhlyash_emoji`

---

*Файл обновляется в начале каждой рабочей сессии. Следующий Claude: читай этот файл первым!*