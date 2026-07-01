
# diet_platform - Claude Context
**Generated:** 2026-06-30 11:46




## Last Checkpoint
**Синхронизация после параллельной работы. Прочитан TEAM_NOTES.md — обнаружено что баг с Userbot Relay (который я нашёл и зарепортил в предыдущем ответе) уже закрыт параллельной сессией (коммит 5f607c5, мой f27ee9f лёг под ним в истории без конфликтов). Не поверил тексту чекпоинта на слово — живьм вызовом send_notification() подтвердил True за 0.54s. Проверил aiogram getUpdates конфликт у den4ik-claude — за 2 часа ни одного события, похоже исчез. Проверил bot token (8954955644, засвечён открытым текстом в чате) — всё ещё жив, не отозван сам, решение оставлено владельцу (downtime-risk операция). Начал было смотреть F2 (timezone) — подтверждён хардкод Europe/Moscow везде, но саму реализацию не начал — решил спросить приоритеты у Denis перед тем как уходить в бэклог без явного запроса (его сообщение было 'TEAM_NOTES / ctx restore / ctx start' — сигнал на синхронизацию, не на дальнейший разработки). Сервисы проверены active, живых изменений в git не вносилось (только .claude/claude.md локально изменён, не трогал).**
_2026-06-30T11:46 | claude_


Next steps:
- [ ] E1: передать weight_kg/health_notes/goal в fitness/engine.py промпт — приоритет безопасности
- [ ] I2: запрет выдумывать детали в SYS_PUHLYASH/SYS_DIET
- [ ] F2: timezone в user_profiles + per-user APScheduler — подтверждён хардкод Europe/Moscow, реализация не начата — ждёт приоритизации от Denis
- [ ] Groq: обновить протухшие ключи GROQ_K1..K5 на console.groq.com — всё ещё не проверено ни в одной сессии
- [ ] I1: modules/irisochka/persona.py по образцу puhlyash/persona.py — ЧАСТИЧНО СДЕЛАНО в modules/puhlyash/irisochka.py в этой сессии (коммит f27ee9f) — проверить пересекается ли с этим next_step или он устарел
- [ ] RESOLVE: bot token 8954955644 засвечён в чате, жив и рабочий (проверено getMe) — решить ротацию с Denis, ротация = downtime для живых пользователей
- [ ] CLOSED: aiogram getUpdates conflict у den4ik-claude — проверено, 2 часа без событий, похоже исчез с переходом на leviathan_hub_bot.py — можно убрать из next_steps
- [ ] Убрать userbot_relay_token из config/.env если роллбэк точно не понадобится — без изменений




## Architectural Decisions

**integration:** Userbot Relay и Pyrogram полностью убраны. modules/notifier/sender.py теперь использует собственный aiogram Bot() diet_platform (короткоживущий инстанс на каждую отправку). Никакой зависимости от den4ik-claude больше нет. userbot_relay_token оставлен в config для быстрого rollback, но не используется. Коммит 5f607c5.
> Что делать после того как den4ik-claude мигрировал на leviathan_hub_bot.py и сломал Userbot Relay (Pyrogram больше не запущен)?

**database:** aiosqlite.connect() всегда с timeout=30. Алиасы DB_PATH (_DB, db_path и др.) должны проверяться вручную: sed-фикс искал только литерал DB_PATH и пропустил алиас _DB.
> Почему возникает database is locked?

**llm:** LLMFactory.execute_request() для всех LLM-вызовов в проекте. Нельзя читать ключи regex'ом из .env. Нельзя делать urllib.request синхронно. ISSUE-03 закрыт: 5 файлов полностью переведены.
> Как делать LLM-вызовы в diet_platform?

**integration:** Userbot Relay: den4ik-claude остаётся единственным владельцем Pyrogram-сессии. Внутри его asyncio.gather() запущен мини-FastAPI на 127.0.0.1:8190. diet_platform шлёт httpx POST /relay/send с X-Relay-Token. Полное слияние отклонено: разные blast radius (den4ik-claude имеет systemctl-права над всеми сервисами).
> Как объединить два проекта владельца для отправки Telegram-сообщений через один Pyrogram userbot?






