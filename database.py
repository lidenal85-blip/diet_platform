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
