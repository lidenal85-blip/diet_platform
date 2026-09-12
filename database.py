"""SQLite schema + migrations. Transactional Outbox pattern."""
import aiosqlite
from building_blocks.config import get_settings
from building_blocks.logger import get_logger

log = get_logger(__name__)
DB_PATH = get_settings().database_path


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Search sessions (SearchQuery aggregate)
CREATE TABLE IF NOT EXISTS search_sessions (
    id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    user_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    error_message TEXT
);

-- Transactional Outbox (pipeline queue)
CREATE TABLE IF NOT EXISTS outbox (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    scheduled_at TEXT NOT NULL DEFAULT (datetime('now')),
    processed_at TEXT,
    error TEXT
);

-- Dead Letter Queue
CREATE TABLE IF NOT EXISTS dlq (
    id TEXT PRIMARY KEY,
    outbox_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    reason TEXT NOT NULL,
    failed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Web page snapshots
CREATE TABLE IF NOT EXISTS web_snapshots (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    raw_text_length INTEGER NOT NULL DEFAULT 0,
    http_status INTEGER NOT NULL DEFAULT 200,
    scraped_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Diet drafts
CREATE TABLE IF NOT EXISTS diet_drafts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    diet_name TEXT NOT NULL,
    confidence_score REAL NOT NULL DEFAULT 0.0,
    raw_payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Diet master (source of truth)
CREATE TABLE IF NOT EXISTS diet_master (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    trace_id TEXT,
    source_url TEXT,
    content_sha256 TEXT UNIQUE,
    diet_name TEXT NOT NULL,
    allowed_foods TEXT NOT NULL DEFAULT '[]',
    forbidden_foods TEXT NOT NULL DEFAULT '[]',
    menu_structure TEXT NOT NULL DEFAULT '{}',
    contraindications TEXT NOT NULL DEFAULT '[]',
    conditions TEXT NOT NULL DEFAULT '[]',
    confidence_score REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'pending_verification',
    version INTEGER NOT NULL DEFAULT 1,
    is_verified INTEGER NOT NULL DEFAULT 0,
    verified_by TEXT,
    verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'system',
    old_value TEXT,
    new_value TEXT,
    trace_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_outbox_status_scheduled
    ON outbox(status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_diet_master_status
    ON diet_master(status);
CREATE INDEX IF NOT EXISTS idx_diet_master_name
    ON diet_master(diet_name);
CREATE INDEX IF NOT EXISTS idx_sessions_status
    ON search_sessions(status);
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.executescript(SCHEMA)
        # Phase 0 (C-2): user_profiles v2 — пререквизит для 3 новых колонок
        # (идемпотентно; на проде таблица уже существует — CREATE IF NOT EXISTS no-op)
        await db.executescript(USER_PROFILES_V2_SCHEMA)
        # Phase 0 (C-2): 4 таблицы planner-домена + обязательные инварианты (ADR-1/2/3/7)
        await db.executescript(PHASE0_SCHEMA)
        await _ensure_profile_phase0_columns(db)
        await db.commit()
    log.info("Database initialized: %s", DB_PATH)


async def get_db():
    """Async context manager for DB connection."""
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        yield db
# v2: Recipes
RECIPES_SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    mode TEXT NOT NULL,           -- quick/home/restaurant/pp
    description TEXT,
    ingredients TEXT NOT NULL,    -- JSON list
    steps TEXT NOT NULL,          -- JSON list
    calories_per_serving INTEGER,
    protein_g REAL,
    fat_g REAL,
    carbs_g REAL,
    cook_time_minutes INTEGER,
    servings INTEGER DEFAULT 2,
    tags TEXT,                    -- JSON list
    source TEXT DEFAULT 'gemini',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fridge_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    ingredients TEXT NOT NULL,    -- JSON list
    recipe_id TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now'))
);
"""


# ── Phase 0 (C-2): planner domain schema — ARCHITECTURE_PHASE0_2026-09.md ──
# DDL зеркалит идемпотентные _ensure_* в planner/ (единый источник структуры).
# Adдитивно: ничего из существующего не изменяется и не удаляется.

USER_PROFILES_V2_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_profiles (
    tg_id TEXT PRIMARY KEY,
    name TEXT, age INTEGER, gender TEXT,
    weight_kg REAL, height_cm REAL, goal TEXT,
    health_notes TEXT, location TEXT,
    cuisine_prefs TEXT DEFAULT '[]',
    excluded_foods TEXT DEFAULT '[]',
    track_cycle INTEGER DEFAULT 0,
    cycle_start_date TEXT, cycle_length_days INTEGER DEFAULT 28,
    email TEXT, phone TEXT,
    onboarding_done INTEGER DEFAULT 0,
    onboarding_step TEXT DEFAULT 'start',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

PHASE0_SCHEMA = """
-- ADR-1: пользовательская программа питания
CREATE TABLE IF NOT EXISTS diet_programs (
    id          TEXT PRIMARY KEY,
    tg_id       TEXT NOT NULL,
    diet_name   TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'llm',   -- llm | heuristic | registry
    card        TEXT NOT NULL DEFAULT '{}',    -- JSON карточки
    constraints_json TEXT NOT NULL DEFAULT '{}', -- снимок контекста выбора (без health_notes)
    status      TEXT NOT NULL DEFAULT 'active',-- active | paused | completed | replaced
    started_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);
-- PATCH-3 (обязательный DB-инвариант): максимум одна active-программа на пользователя
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_program_per_user
    ON diet_programs(tg_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_diet_programs_user ON diet_programs(tg_id, status);

-- ADR-2: недельный план с календарными границами (PATCH-1)
CREATE TABLE IF NOT EXISTS weekly_plans (
    id          TEXT PRIMARY KEY,
    program_id  TEXT NOT NULL,
    tg_id       TEXT NOT NULL,
    week_no     INTEGER NOT NULL DEFAULT 1,
    start_date  TEXT NOT NULL,                 -- 'YYYY-MM-DD' в tz пользователя
    end_date    TEXT NOT NULL,                 -- start_date + 6 дней
    days        TEXT NOT NULL DEFAULT '[]',    -- JSON: формат генератора (не нормализуем)
    shopping_list TEXT NOT NULL DEFAULT '[]',
    tips        TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL DEFAULT 'active',-- active | archived
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
-- PATCH-3 (обязательный DB-инвариант): одна active-неделя на программу
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_plan_per_program
    ON weekly_plans(program_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_weekly_plans_program ON weekly_plans(program_id, week_no);
CREATE INDEX IF NOT EXISTS idx_weekly_plans_user ON weekly_plans(tg_id, status);

-- ADR-3: planned meal (materialized только для фактических слотов — PATCH-4)
CREATE TABLE IF NOT EXISTS meal_state (
    id           TEXT PRIMARY KEY,
    tg_id        TEXT NOT NULL,
    plan_id      TEXT NOT NULL,
    day_date     TEXT NOT NULL,               -- 'YYYY-MM-DD' в tz пользователя (PATCH-10)
    day_name     TEXT,
    meal_slot    TEXT NOT NULL,               -- breakfast | lunch | dinner | snack
    planned_ref  TEXT NOT NULL DEFAULT '{}',  -- JSON {"day_index":i,"meal":slot}
    planned_text TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'planned', -- planned|eaten|skipped|replaced|missed
    recipe_id    TEXT,
    replace_to   TEXT,
    note         TEXT,
    status_changed_at TEXT,
    UNIQUE(plan_id, day_date, meal_slot)
);
CREATE INDEX IF NOT EXISTS idx_meal_state_user_day ON meal_state(tg_id, day_date);

-- ADR-7: события (минимальная таксономия Phase 0 — PATCH-9; ts = UTC — PATCH-10)
CREATE TABLE IF NOT EXISTS events (
    id    TEXT PRIMARY KEY,
    tg_id TEXT,
    name  TEXT NOT NULL,
    props TEXT NOT NULL DEFAULT '{}',
    ts    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_name_ts ON events(name, ts);
"""

# §13: ровно 3 новые колонки user_profiles (ADR-5); backfill НЕ делается
PROFILE_PHASE0_COLUMNS = [
    "restrictions TEXT",
    "activity TEXT",
    "timezone TEXT DEFAULT 'Europe/Moscow'",  # fallback для legacy/unknown (ADR-6)
]


async def _ensure_profile_phase0_columns(db: aiosqlite.Connection) -> None:
    """Идемпотентное добавление 3 колонок (паттерн puhlyash_settings._ensure_columns)."""
    for col in PROFILE_PHASE0_COLUMNS:
        try:
            await db.execute(f"ALTER TABLE user_profiles ADD COLUMN {col}")
        except Exception:
            pass  # колонка уже существует — идемпотентность
