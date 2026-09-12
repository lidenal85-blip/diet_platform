# ПРОМПТ 6 (консолидированный) — Финальный аудит отчёта Product Positioning + Architecture Impact Review перед продолжением C-2

> **Статус:** рабочая инструкция. Единый документ, собранный из трёх вариантов промпта 6 (они содержательно идентичны, различаются строгостью формата).
> **Как работать:** строго по этапам E0 → E1 → E2 → E3 → E4 → E5. Этапы не смешивать: сначала всё доказательство (E0–E2), затем аудиторский отчёт (E3), только после него план правок (E4) и резюме (E5).
>
> **Разбиение на проходы (для снижения нагрузки):** работу можно делить на проходы —
> проход 1: E0–E1 + сбор доказательств A1–A6; проход 2: доказательства A7–A12 + C-01…C-06 + Data Gaps; проход 3: E3 (AUDIT REPORT); проход 4: E4 + E5.
> Делить на проходы — можно; смешивать этапы в одном проходе — нельзя. Рабочие находки E2 владельцу как итоговый результат не поставляются — только E3 и E4.
>
> **Правило read-only:** на протяжении E0–E3 никакие файлы проекта не изменяются (код, документы, схема). Правки применяются только после подтверждения владельцем CHANGE PLAN из E4 (отдельная авторизация — как C-1/C-2).

---

## E0. Подготовка (контекст и роль)

**Роль:** Senior Product Architect + Systems Architect + Technical Auditor.

**Объект аудита:** отчёт «Product Positioning + Architecture Impact Review» (выполнен по `promts/5.md`), который проверяет встраивание нового продуктового замысла владельца в текущую архитектуру перед продолжением C-2.

**Новый продуктовый замысел владельца (owner concept, promts/5.md):**
«Пухляш» расширяется из nutrition/meal-planning продукта в мульти-доменный продукт:
- Nutrition (текущий реализуемый домен)
- Culinary / Recipes
- Fitness
- Characters
- Social recognition
- Independent statuses
- Future entitlements / limits
- Future purchases / subscription

**Канонические персонажи (owner canon):**
- Пухляш = рыжий/оранжевый упитанный кот. Зона: еда, удовольствие, комфорт, кулинарные эксперименты, рецепты, авторские рецепты, кулинарный контент.
- Ирисочка = фитоняшка. Это канон. Она **НЕ мышь**.
- Старое «Ирисочка = мышь» в коде/доках — legacy contradiction → исправление откладывается в Character Bible / Phase 3, C-2 не касается.

**Фактическое состояние C-2 (заявленное, подлежит перепроверке по первичным источникам):**
- создан `planner/` (tz, programs, plans, slots, context, events)
- 4 новые таблицы, 2 partial unique indexes, 3 новых поля в `user_profiles`
- 31 тест, 31/31 проходят (заявление — перепроверить фактическим запуском)
- handlers не подключены, deploy не выполнялся, изменения не закоммичены

**Цепочка Nutrition domain:**
```
diet_programs → weekly_plans → meal_state
```
`events` — доменно-агностический журнал событий.

**Главная задача аудита:** проверить, действительно ли новый продуктовый замысел требует изменения C-2, что утверждения отчёта подтверждены первичными источниками, что гипотезы не превратились в архитектуру, а неизвестные остались неизвестными.

---

## E1. Правила доказательности (применять на всех этапах)

### 1.1. Приоритет источников — текущее техническое состояние
Только первичные источники:
1. **CODE** — фактический код
2. **DATABASE** — фактическая схема и данные БД
3. **RUNTIME** — реально работающие сервисы/процессы/endpoints/конфигурация
4. **TEST** — фактические тесты и результат их запуска
5. **GIT** — branch, commits, diff, status
6. **DOCUMENT** — архитектурные документы, планы, отчёты

**Сам аудируемый отчёт НЕ является первичным источником текущего технического состояния.**
- «31/31 тестов проходят» — только утверждение, пока не подтверждено TEST (фактическим запуском в рамках аудита).
- «C-2 не подключён к handlers» — только утверждение, пока не подтверждено CODE/RUNTIME.

### 1.2. Приоритет источников — продуктовые решения
1. **OWNER** — прямое решение владельца продукта
2. **DOCUMENT** — ранее зафиксированное решение
3. **OBSERVATION** — наблюдение
4. **INFERENCE** — вывод аудитора

Уточнение источников: прямые утверждения и фиксации владельца в `promts/5.md` / `promts/6.md` (авторство владельца) считаются **OWNER**; все остальные документы (стратегия, backlog, архитектурные отчёты) — **DOCUMENT**.

Старый документ **не считается** актуальным owner decision, если более новое прямое решение владельца ему противоречит. Нельзя автоматически считать старое значение (например, D30 ≥ 15%) подтверждённым новым owner concept.

### 1.3. Жёсткое разделение FACT / INTERPRETATION / DECISION / UNKNOWN
Для каждого существенного утверждения:
- **FACT** — что непосредственно подтверждено источником.
- **INTERPRETATION** — что из этого следует. Нельзя записывать интерпретацию как факт.
- **DECISION** — только если решение реально принято.
- **UNKNOWN** — если данных недостаточно.

Пример корректной записи:
```
FACT: В текущей таблице recipes отсутствует author/owner. (CODE)
INTERPRETATION: Если появится подтверждённый UGC-сценарий, recipe domain,
вероятно, потребует моделирования ownership.
STATUS: UNKNOWN / SPEC
DECISION: Не менять C-2 schema до Product Gate.
```
Запрещено: «Recipes готовят пользователи, поэтому нужна таблица authors».

### 1.4. Правила для недоступных источников
Если источник отсутствует/не загружен/не читается/команда не выполняется/runtime или БД не проверить/тесты не запустить/источник извлекается противоречиво — то **ЗАПРЕЩЕНО**:
- считать утверждение подтверждённым;
- восстанавливать содержимое по памяти;
- делать вид, что источник был проверен;
- использовать аудируемый отчёт как замену первичному источнику;
- повышать confidence по косвенным признакам.

**ОБЯЗАТЕЛЬНО** создать запись:
```
[UNKNOWN]
Type: FACT
Statement: ...
Why: Первичный источник недоступен.
Evidence Checked: ...
Impact: LOW | MEDIUM | HIGH | CRITICAL
Can Defer: YES | NO
Next Action: Получить/проверить источник.
```
Если недоступный источник компенсируется независимым подтверждением из другого первичного источника — указать это явно (отсутствие одного источника не делает факт неизвестным, если он подтверждён другим).

### 1.5. «НЕ ПРОВЕРЕНО» ≠ «НЕ СУЩЕСТВУЕТ»
- Источник не проверен → «Не подтверждено».
- Таблица не найдена после фактической проверки БД → «Таблица отсутствует».
- Код не найден после проверки соответствующего scope → «Реализация не обнаружена в проверенном scope».
- Запрещено делать глобальные выводы из неполного scope.

### 1.6. Таксономия утверждений (единственная допустимая)
```
[FACT]          Confidence: HIGH|MEDIUM|LOW
                Source: CODE|DATABASE|RUNTIME|TEST|GIT|DOCUMENT|OWNER|OBSERVATION
                Evidence: ...

[HYPOTHESIS]    Confidence: HIGH|MEDIUM|LOW
                Based on: ...

[RECOMMENDATION] Экспертная рекомендация. Не выдаётся за решение владельца.

[DECISION]      Owner: PRODUCT|ARCHITECTURE|TECHNICAL
                Basis: ...

[CONFLICT]      Sources: ...
                Conflict: ...
                Impact: ...
                Resolution: ...

[UNKNOWN]       Type: FACT|DECISION|SPEC|STALE|BLOCKER
                Statement: ...
                Why: ...
                Evidence Checked: ...
                Impact: LOW|MEDIUM|HIGH|CRITICAL
                Can Defer: YES|NO
                Next Action: ...
```
Запрещены собственные категории («MISSING FACT», «UNCONFIRMED», «SAFETY UNKNOWN» и т.п.) — для них используется `[UNKNOWN]` с соответствующим Type. Не смешивать неизвестность и гипотезу: UNKNOWN = данных нет; HYPOTHESIS = предположение при недостатке данных.

### 1.7. Порог архитектурных решений
Новые постоянные доменные сущности/таблицы/связи (author/ownership, publication, moderation, status, rewards, entitlements, quotas, balances, purchases, subscriptions, reputation, social graph, multi-currency economy) требуют **HIGH-confidence evidence ИЛИ явного [DECISION]**. Не проектировать «на будущее», если Product Gate не пройден.

**Главный принцип:** «Сначала установить факт. Затем отдельно сформулировать интерпретацию. Затем определить, есть ли решение. И только после этого решать, нужна ли правка архитектуры.» Не улучшать систему предположениями. Не выдавать отсутствие проверки за отсутствие факта.

---

## E2. ЭТАП I — АУДИТ (план правок на этом этапе НЕ составляется)

Для каждого существенного замечания:
```
ID:
Severity: LOW | MEDIUM | HIGH | CRITICAL
Type: FACT | HYPOTHESIS | RECOMMENDATION | DECISION | CONFLICT | UNKNOWN
Claim:
Evidence:
Assessment:
Impact:
```

**Связка находок с отчётом:** блоки выше — рабочие заметки этапа I. В итоговый отчёт (E3) каждая находка попадает в одну из таблиц §3–§7 (Facts / Interpretations / Decisions / Conflicts / Unknowns) без дублирования рабочего блока; для противоречий C-01…C-06 используется их собственный формат (Sources/Conflict/…). Отдельного раздела «находки с Severity» в отчёте НЕТ.

### Проверяемые области (A1–A12)

**A1. Product Positioning.** Для каждого домена — Nutrition, Culinary, Fitness, Characters, Social, Economy — определить: текущий реализуемый домен / подтверждённое направление / гипотеза / будущее направление. Будущие домены не получают автоматически тот же архитектурный статус, что Nutrition. Nutrition не считается моделью всего продукта.

**A2. Nutrition / C-2 модель.** Проверить `diet_programs → weekly_plans → meal_state` и: active program, active weekly plan, meal slots, plan → meal связь, canonical today query, profile context, timezone, events. Проверить, что `planner/` не становится «ядром всего продукта»: корректное позиционирование — **«Planner — Nutrition / Planning domain module»**.

**A3. Фактическое состояние C-2.** Перепроверить по первичным источникам каждый пункт: наличие `planner/` и конкретных файлов; новые таблицы; partial unique indexes; новые поля; количество тестов; **фактический результат запуска тестов** (не по памяти и не по отчёту); handlers; production wiring; deploy; git status; commits. Каждый факт — с первичным источником.
- Если фактический запуск тестов в среде аудита невозможен — это НЕ «тесты подтверждены»: фиксируется [UNKNOWN] по правилу 1.4, TEST помечается PARTIAL/UNAVAILABLE в EVIDENCE COVERAGE. То же для DATABASE/RUNTIME сервера (whimco): доступ не удался → PARTIAL/UNAVAILABLE, а не «подтверждено по памяти».

**A4. Recipes.** Проверить текущую schema `recipes`, наличие author/owner (фиксировать как фактический migration hotspot, если отсутствует), publication, moderation, связь recipes ↔ meal_state (`meal_state.recipe_id`). **Не проектировать authorship сейчас.** Корректная формулировка будущего риска: «Recipe domain архитектурно допускает развитие, но конкретные изменения схемы для ownership, authorship, publication и moderation не определены». Запрещён вывод «будущая авторская модель просто аддитивна».

**A5. Characters.** Канон: Пухляш = кот, Ирисочка = фитоняшка. Проверить legacy contradiction «Ирисочка = мышь» в коде/доках, определить, влияет ли она на C-2 (ожидание: нет, исправление в Character Bible / Phase 3).

**A6. 🥞 Блинчики.** Проверить трактовку: 🥞 = reaction / recognition, НЕ wallet/currency. Все числа («100 🥞 → 1 🎂», «10 🎂 → 1 month free») — SPEC UNKNOWN, если владелец их явно не зафиксировал.

**A7. 🔥.** Проверить внутреннюю согласованность: если принято «🔥 не является второй валютой» (активность = events/streaks/activity history/derived metrics), то в отчёте не должно остаться открытого вопроса «🔥 currency vs events/streaks?» — это внутреннее противоречие, подлежащее удалению.

**A8. Status.** Проверить, что будущие статусы (Culinary: 🥣 Поварёнок … 👑 Маэстро кухни; отдельно Fitness) не стали текущей архитектурой. НЕ подтверждены без owner decision: названия уровней, порядок, пороги, функциональные преимущества, связь статуса с entitlement. Проверить отсутствие преждевременных: status columns в `user_profiles`, status tables, reward ledger, reputation engine.

**A9. Economy.** Проверить разделение **entitlement ≠ status ≠ balance ≠ purchase** (право на бесплатное использование ≠ статус ≠ баланс ≠ покупка/подписка). Отдельно проверить источник **D30 ≥ 15%** как monetization gate: OWNER decision / DOCUMENT fact / recommendation / stale assumption — не называть owner decision без прямого подтверждения. Практический вывод сейчас: платежи/подписка/покупки не реализуются; архитектура только не должна им препятствовать.

**A10. Fitness.** Проверить, что Fitness не проталкивается в C-2. Направление `exercise → workout → completion → progress → status` — product direction, не основание для текущей schema. Отметить safety unknowns (contraindications, intensity) для будущего Fitness domain.

**A11. Social.** Проверить, что не создаются преждевременно: social graph, followers, reputation engine, ranking, полноценная лента. Social loop `create → publish → recognition → reputation → return` — **гипотеза, а не доказанный retention loop**; при ~2 пользователях сильных выводов делать нельзя.

**A12. Events.** Проверить `events` как generic event log. Будущие имена (`recipe_published`, `recipe_cooked`, `recipe_reacted`, `fitness_workout_started/completed`, `economy_entitlement_granted` и т.п.) — доменные префиксы, не требующие отдельных таблиц сейчас. Формулировать как **архитектурную политику**, а не как обещание «схема гарантированно никогда не изменится».

### Contradiction Audit (минимум C-01…C-06)
Для каждого: `Sources / Conflict / Impact / INTERPRETATION / Which source has priority / Resolution`:
- **C-01** старый product scope («social/community не строить», «cookbook — не библиотека», «не строить платежи до D30 ≥15%») ↔ новый owner concept. Определить: что устарело, что валидно, какие ограничения сохраняются.
- **C-02** Ирисочка «мышь» ↔ Ирисочка «фитоняшка». Приоритет — owner canon; код не трогать в C-2.
- **C-03** Nutrition как весь продукт ↔ Nutrition как один домен (текущий core). Planner = Nutrition domain module.
- **C-04** старый monetization gate ↔ новый owner concept. Проверить источник D30 ≥15%.
- **C-05** 🔥 currency ↔ events/streaks. Не допускать одновременно «решено не делать» и «решение открыто».
- **C-06** Recipes как часть meal execution ↔ самостоятельный Culinary domain. Модель сосуществования: `Recipe domain → meal_state.recipe_id` (Recipe — самостоятельный домен, используемый Nutrition planner).

### Data Gaps (после аудита)
Таблица: `ID | Unknown | Type | Why Important | Impact | Can Defer | Next Action`.
Минимум проверить: публикацию пользовательских рецептов; recognition; влияние recognition на retention; функциональный смысл статусов; модель fitness entitlement; free limits; status thresholds; правила 🥞; verified cooking event; moderation policy; fitness safety policy; статус D30 ≥15% (owner decision или старая рекомендация).

### Форма EVIDENCE COVERAGE (в итоговом отчёте)
```
CODE:      VERIFIED | PARTIAL | UNAVAILABLE
DATABASE:  VERIFIED | PARTIAL | UNAVAILABLE
RUNTIME:   VERIFIED | PARTIAL | UNAVAILABLE
TEST:      VERIFIED | PARTIAL | UNAVAILABLE
GIT:       VERIFIED | PARTIAL | UNAVAILABLE
DOCUMENT:  VERIFIED | PARTIAL | UNAVAILABLE
OWNER:     VERIFIED | PARTIAL | UNAVAILABLE
```
+ Evidence quality (HIGH/MEDIUM/LOW/INSUFFICIENT) + важные ограничения источников.

---

## E3. Финальный итог аудита — жёсткий формат (без доп. разделов до/после)

```
# AUDIT REPORT

## 1. VERDICT
Status: GO | GO WITH CHANGES | BLOCKED
One-line reason: ...

## 2. EVIDENCE COVERAGE
(по форме из E2; quality; limitations)

## 3. VERIFIED FACTS
| ID | Fact | Source | Confidence | Evidence |
(только подтверждённые факты, без интерпретаций)

## 4. INTERPRETATIONS
| ID | Interpretation | Based on Facts | Confidence |
(только выводы аудитора)

## 5. DECISIONS
| ID | Decision | Owner | Basis |
(только реально подтверждённые решения)

## 6. CONFLICTS
| ID | Sources | Conflict | Impact | Resolution |

## 7. UNKNOWNS / DATA GAPS
| ID | Unknown | Type | Impact | Can Defer | Next Action |

## 8. C-2 IMPACT
Current C-2: UNCHANGED | DOCUMENTATION ONLY | CHANGES REQUIRED | BLOCKED
Required technical changes: ...
Technical changes explicitly NOT required: ...

## 9. AUDIT CONCLUSION
(3–7 коротких пунктов, только выводы из разделов выше)
```

**Финальный вердикт — только один:** GO (продолжать без изменений) / GO WITH CHANGES (минимальные изменения до продолжения) / BLOCKED (реально блокирует; не называть блокером то, что безопасно откладывается). Правило «без дополнительных разделов» относится к самому деливераблу AUDIT REPORT; резюме E5 — отдельное сообщение после E4, а не раздел отчёта.

Ожидаемая проверка вердикта: остаётся ли корректным **GO WITH CHANGES** с минимальными документальными изменениями:
1. `planner/__init__.py` — уточнить позиционирование Nutrition / Planning domain module.
2. `planner/events.py` — зафиксировать политику будущих доменных event names.
3. C-2 plan — указать, что authorship/status/economy относятся к будущим Product Gates.
4. Вынести legacy contradiction Ирисочки в Phase 3.
5. Удалить внутреннее противоречие по 🔥.
6. Исправить формулировку про будущие миграции («не требует изменений схемы для C-2; будущие домены могут потребовать аддитивных миграций после Product Gates», а не «не требует миграций вообще»).
7. Не превращать D30 ≥15% в owner decision без подтверждения.
8. Зафиксировать `recipes.author/ownership` как будущий migration hotspot, не меняя C-2 schema.

⚠️ Этот список — **контрольная точка, а не предустановленный вывод**: если аудит покажет, что пункт не нужен, или обнаружит новую проблему — вердикт и список меняются по фактам аудита, а не по ожиданиям.

---

## E4. ЭТАП II — ПЛАН ПРАВОК (только после завершения AUDIT REPORT)

Не повторять аудит. Не анализировать факты заново. Составить **минимальный** план правок в отчёте и документации.

```
# CHANGE PLAN

## A. BEFORE C-2 CONTINUES (обязательные, до продолжения)
| ID | Priority | Target | Required Change | Reason | Evidence | C-2 Impact |

## B. AFTER C-2 (документальные/продуктовые, не блокируют)
| ID | Priority | Target | Required Change | Reason | Evidence |

## C. FUTURE PRODUCT GATES (отложить до Gate)
| ID | Domain | Decision Needed | Why Not Now |
(authorship, publication, moderation, statuses, rewards, entitlements,
fitness, social, economy, purchases, subscription)

## D. DO NOT IMPLEMENT NOW
| Item | Reason |
(преждевременное архитектурное усложнение)

## E. FINAL ACTION
NEXT ACTION: ...
C-2 STATUS: CONTINUE | CONTINUE AFTER DOCUMENT FIXES | STOP
```

Шкала приоритетов: **P0** — без правки страдает корректность C-2 или самого отчёта (раздел A); **P1** — документальная/продуктовая несогласованность, C-2 не блокирует (раздел B); **P2** — отложенное улучшение/отслеживание (разделы C/D). Приоритет и раздел плана не должны противоречить друг другу.

Формат каждой правки:
```
ID:
Priority: P0 | P1 | P2
Target:
Current problem:
Required change:
Why:
Source / Evidence:
C-2 impact: NONE | LOW | MEDIUM | HIGH
```

---

## E5. Краткий финал ответа (4 блока)

1. **Audit Verdict** — что показал аудит.
2. **Evidence Quality** — насколько подтверждены факты текущего состояния и где пробелы.
3. **Change Plan** — минимальный список правок.
4. **C-2 Decision** — можно ли продолжать C-2 и при каких условиях.

---

## E6. Критические ограничения (15)

1. Не считать аудируемый отчёт первичным доказательством собственного утверждения.
2. Не превращать интерпретацию в факт.
3. Не превращать гипотезу в решение.
4. Не превращать старый документ автоматически в актуальное owner decision.
5. Недоступный источник = неподтверждённое утверждение, если нет другого достаточного первичного доказательства.
6. «Не проверено» ≠ «не существует».
7. Не проектировать будущие домены «на всякий случай».
8. Не менять C-2 schema из-за неподтверждённых будущих требований.
9. Не добавлять status/economy/social/reputation сущности без соответствующего Product Gate.
10. Не добавлять новые архитектурные обязательства только потому, что они логично выглядят.
11. Недостаточно доказательств → `[UNKNOWN]`.
12. Источники противоречат → не выбирать удобный; оформить `[CONFLICT]` с приоритетом источников.
13. Факт из единственного слабого/устаревшего источника не повышается до HIGH.
14. Недоступный источник явно указывается в EVIDENCE COVERAGE.
15. План правок формируется только после завершения аудита.

**Главное правило:** «Не улучшай архитектуру без доказанной необходимости. Не превращай гипотезы нового продукта в технические обязательства текущего C-2. При недостатке данных лучше явно оставить неизвестность, чем незаметно превратить предположение в архитектуру.»
