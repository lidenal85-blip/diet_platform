
# diet_platform - Claude Context
**Generated:** 2026-06-30 10:16




## Last Checkpoint
**GROQ 401 в diet_platform: найден и исправлен реальный баг (не просто протухший ключ). _groq_pool() и _gemini_pool() в /opt/leviathan_engine/llm_factory.py абортировали весь retry-цикл после первого неудачного ключа вместо перехода к следующему в пуле. Цепочка: 1 из 14 Gemini-ключей (...1SIf9M) suspended → фоллбэк на Groq → 1 из 5 Groq-ключей дал тот же баг → полный отказ. Исправлено 3 патча: (1) core/key_pool.py — добавлен COOLDOWN_401_SEC=3600 и ветка elif code==401; (2) llm_factory.py _groq_pool — raise→warning+continue; (3) llm_factory.py _gemini_pool — та же замена. Синтаксис проверен py_compile. diet-platform.service перезапущен 2 раза (каждый ~90с из-за медленного SIGTERM), финально active/running, /health → 200, логи чистые без ошибок. Прямые тесты GROQ_K1..K5 — 5/5 валидны.**
_2026-06-30T10:16 | claude_


Next steps:
- [ ] Идентифицировать и при желании перевыпустить подозрительный Gemini-ключ (суффикс ...1SIf9M, 403 Consumer suspended) — не срочно, теперь корректно пропускается благодаря cooldown-фиксу
- [ ] Проверить/перезапустить другие сервисы, использующие общий /opt/leviathan_engine/llm_factory.py, чтобы подхватить тот же фикс (не сделано в этой сессии, вне скопа)
- [ ] Отдельно: diet-platform.service ~90с виснет в deactivating (stop-sigterm) при каждом рестарте — вероятно нет graceful shutdown для scheduler/aiogram polling/pipeline_worker. Не критично, но стоит починить если рестарты участятся.
- [ ] Открытый бэклог из предыдущего чекпоинта (E1/I2/F2/G1-G2/A1-A3 и т.д.) остаётся открытым, эта сессия его не касалась




## Architectural Decisions

**database:** aiosqlite.connect() всегда с timeout=30. Алиасы DB_PATH (_DB, db_path и др.) должны проверяться вручную: sed-фикс искал только литерал DB_PATH и пропустил алиас _DB.
> Почему возникает database is locked?

**llm:** LLMFactory.execute_request() для всех LLM-вызовов в проекте. Нельзя читать ключи regex'ом из .env. Нельзя делать urllib.request синхронно. ISSUE-03 закрыт: 5 файлов полностью переведены.
> Как делать LLM-вызовы в diet_platform?

**integration:** Userbot Relay: den4ik-claude остаётся единственным владельцем Pyrogram-сессии. Внутри его asyncio.gather() запущен мини-FastAPI на 127.0.0.1:8190. diet_platform шлёт httpx POST /relay/send с X-Relay-Token. Полное слияние отклонено: разные blast radius (den4ik-claude имеет systemctl-права над всеми сервисами).
> Как объединить два проекта владельца для отправки Telegram-сообщений через один Pyrogram userbot?






