PRAGMA journal_mode=WAL;
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
CREATE TABLE IF NOT EXISTS recipe_sessions (
    id TEXT PRIMARY KEY, tg_id TEXT NOT NULL,
    mode TEXT NOT NULL, request_text TEXT NOT NULL,
    result_json TEXT, status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS shopping_lists (
    id TEXT PRIMARY KEY, tg_id TEXT NOT NULL,
    recipe_session_id TEXT,
    items_json TEXT NOT NULL DEFAULT '[]',
    budget REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_user_profiles_tg ON user_profiles(tg_id);
CREATE INDEX IF NOT EXISTS idx_recipe_sessions_tg ON recipe_sessions(tg_id);
CREATE INDEX IF NOT EXISTS idx_shopping_tg ON shopping_lists(tg_id);
