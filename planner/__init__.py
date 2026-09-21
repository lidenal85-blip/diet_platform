"""planner — Phase 0 domain module «продукт начинает помнить».

Позиционирование (CP-1, аудит 2026-09-12): planner — модуль домена
Nutrition / Planning, НЕ «ядро всего продукта». Мульти-доменный продуктовый
замысел (promts/5.md) размещает в этом модуле только Nutrition; Culinary,
Fitness, Characters, Social, Economy — отдельные будущие домены со своими
Product Gates.

Слой домена: diet_programs → weekly_plans → meal_state (+ events).
Canonical chain (PATCH-2): user → active diet_program → active weekly_plan
→ meal_state(day_date=today). Прямой запрос meal_state по (tg_id, day_date)
источником истины НЕ является.

C-3.3 (2026-09-21): planner.overview.get_week_overview — недельный обзор
активной недели (read-only зеркало canonical chain) для экрана «Мой план».

Границы C-2: модуль НЕ подключён к handlers/onboarding/LLM — только домен + схема.
"""
from planner.tz import (
    DEFAULT_TZ,
    TimezoneError,
    WeekBoundsError,
    get_user_tz,
    now_utc,
    today_local,
    to_local_date,
    utc_ts_string,
    week_bounds,
    validate_week_dates,
    day_date_for,
)
from planner.programs import (
    ProgramError,
    create_program,
    get_active_program,
    get_program,
    pause_program,
    resume_program,
    complete_program,
    replace_program,
    list_programs,
)
from planner.plans import (
    PlanError,
    create_plan,
    create_plan_from_days,
    get_active_plan,
    get_active_plan_for_user,
    archive_plan,
    list_plans,
)
from planner.slots import (
    SlotsError,
    KNOWN_MEAL_SLOTS,
    MEAL_STATUS_VALUES,
    extract_meal_slots,
    create_meal_states,
    get_today_meals,
    set_meal_status,
    persist_plan_bundle,
)
from planner.overview import get_week_overview
from planner.context import (
    DIET_CONTEXT_FIELDS,
    RECIPE_CONTEXT_FIELDS,
    FITNESS_CONTEXT_FIELDS,
    HEALTH_NOTES_FIELD,
    build_contexts,
    build_diet_context,
    build_recipe_context,
    build_fitness_context,
)
from planner.events import (
    EventError,
    PHASE0_EVENTS,
    FORBIDDEN_PROP_KEYS,
    log_event,
    recent_events,
)

__all__ = [
    # tz
    "DEFAULT_TZ", "TimezoneError", "WeekBoundsError", "get_user_tz", "now_utc",
    "today_local", "to_local_date", "utc_ts_string", "week_bounds",
    "validate_week_dates", "day_date_for",
    # programs
    "ProgramError", "create_program", "get_active_program", "get_program",
    "pause_program", "resume_program", "complete_program", "replace_program",
    "list_programs",
    # plans
    "PlanError", "create_plan", "create_plan_from_days", "get_active_plan",
    "get_active_plan_for_user", "archive_plan", "list_plans",
    # meal_state / canonical chain
    "SlotsError", "KNOWN_MEAL_SLOTS", "MEAL_STATUS_VALUES", "extract_meal_slots",
    "create_meal_states", "get_today_meals", "set_meal_status",
    "persist_plan_bundle",
    "get_week_overview",
    # context
    "DIET_CONTEXT_FIELDS", "RECIPE_CONTEXT_FIELDS", "FITNESS_CONTEXT_FIELDS",
    "HEALTH_NOTES_FIELD", "build_contexts", "build_diet_context",
    "build_recipe_context", "build_fitness_context",
    # events
    "EventError", "PHASE0_EVENTS", "FORBIDDEN_PROP_KEYS", "log_event",
    "recent_events",
]
