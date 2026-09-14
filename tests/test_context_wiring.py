"""§20 step 4 — context-builders connect (PATCH-6 allowlists at call sites).

What the tests pin down:
1. `modules/fitness/engine.py` generate_exercises accepts optional
   `context: dict | None = None` (additive signature); default keeps old
   prompt, allowlist keys are rendered, foreign keys are dropped.
2. `bot_handlers/recipes.py` btn_puhlyash_recipe builds its profile via
   `planner.build_recipe_context()` — allowlist only; health_notes and
   other non-allowlist columns never reach the generator.
3. `bot_handlers/meal_schedule_v2.py` _fire feeds fitness the allowlist
   fitness context (activity/goal), not the raw profile dict (static seam
   check — the closure is APScheduler-registered and not callable in-unit).
"""
import json
import sys
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ))

import database  # noqa: E402
import planner.context as context_mod  # noqa: E402


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Real SQLite DB with the Phase-0 profile columns the allowlists read."""
    db_path = tmp_path / "ctx.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    import sqlite3

    con = sqlite3.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE user_profiles (
            tg_id TEXT PRIMARY KEY,
            restrictions TEXT,
            excluded_foods TEXT,
            cook_level TEXT,
            budget_level TEXT,
            max_cook_time INTEGER,
            activity TEXT,
            goal TEXT,
            health_notes TEXT,
            telegram_name TEXT
        )
        """
    )
    con.execute(
        "INSERT INTO user_profiles (tg_id, restrictions, excluded_foods, cook_level, "
        "budget_level, max_cook_time, activity, goal, health_notes, telegram_name) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("42", "no pork", "mushrooms", "beginner", "low", 30, "medium", "lose_weight", "very-private", "Dima"),
    )
    con.commit()
    con.close()
    return str(db_path)


class _Msg:
    from_user = type("U", (), {"id": 42})()

    async def answer(self, *a, **k):
        return self

    async def delete(self):
        return None


# ── 1. fitness engine: additive context param ────────────────────────────────


@pytest.mark.asyncio
async def test_generate_exercises_accepts_context(monkeypatch):
    import modules.fitness.engine as eng

    captured = {}

    async def fake_gemini(prompt):
        captured["prompt"] = prompt
        return json.dumps(
            [{"name": "Jumping jacks", "reps": "20", "description": "", "caution": ""}]
        )

    monkeypatch.setattr(eng, "_gemini", fake_gemini)

    # Default call: no context fragment in the prompt (old behavior intact)
    await eng.generate_exercises("lunch", "home")
    assert "activity:" not in captured["prompt"]

    # With context: allowlist fields appear in a stable form
    await eng.generate_exercises(
        "lunch", "home", context={"activity": "medium", "goal": "lose_weight"}
    )
    assert "activity: medium" in captured["prompt"]
    assert "goal: lose_weight" in captured["prompt"]
    assert "health_notes" not in captured["prompt"]

    # Foreign keys never reach the prompt even if passed
    await eng.generate_exercises(
        "lunch", "home", context={"activity": "low", "goal": "", "telegram_name": "x"}
    )
    assert "activity: low" in captured["prompt"]
    assert "telegram_name" not in captured["prompt"]


# ── 2. recipes: allowlist context, health_notes never leaves the DB ─────────


@pytest.mark.asyncio
async def test_puhlyash_recipe_uses_recipe_allowlist(tmp_db, monkeypatch):
    import bot_handlers.recipes as recipes_mod
    import modules.puhlyash.persona as persona

    captured = {}

    async def fake_generate(profile=None, diet_name=None, mood=None):
        captured["profile"] = profile
        return {"id": "r1", "title": "T", "description": "", "ingredients": "[]", "steps": "[]"}

    monkeypatch.setattr(persona, "generate_puhlyash_recipe", fake_generate)
    monkeypatch.setattr(recipes_mod, "_save", lambda *_a, **_k: None, raising=False)
    monkeypatch.setattr(recipes_mod, "main_kb", lambda *a, **k: None, raising=False)
    # handler must still build its profile from the real (patched) DB path
    monkeypatch.setattr(recipes_mod, "DB_PATH", tmp_db, raising=False)
    import modules.reactions.engine as reactions_engine
    monkeypatch.setattr(reactions_engine, "reaction_kb", lambda *a, **k: None, raising=False)

    await recipes_mod.btn_puhlyash_recipe(_Msg(), state=None)

    prof = captured["profile"]
    assert prof == {
        "restrictions": "no pork",
        "excluded_foods": "mushrooms",
        "cook_level": "beginner",
        "budget_level": "low",
        "max_cook_time": 30,
    }


@pytest.mark.asyncio
async def test_recipe_allowlist_delegates_to_planner(tmp_db, monkeypatch):
    """The call site must delegate to planner.context, not re-inline its own list."""
    import bot_handlers.recipes as recipes_mod
    import modules.puhlyash.persona as persona
    import modules.reactions.engine as reactions_engine

    seen = {}

    async def fake_build(db, tg_id):
        seen["called"] = True
        return {"cook_level": "beginner"}

    monkeypatch.setattr(context_mod, "build_recipe_context", fake_build)
    # handler calls it via the package namespace (import planner) — patch that ref too
    import planner as planner_pkg
    monkeypatch.setattr(planner_pkg, "build_recipe_context", fake_build, raising=False)

    async def fake_generate(profile=None, diet_name=None, mood=None):
        seen["profile"] = profile
        return {"id": "r1", "title": "T", "description": "", "ingredients": "[]", "steps": "[]"}

    monkeypatch.setattr(persona, "generate_puhlyash_recipe", fake_generate)
    monkeypatch.setattr(recipes_mod, "_save", lambda *_a, **_k: None, raising=False)
    monkeypatch.setattr(recipes_mod, "main_kb", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(reactions_engine, "reaction_kb", lambda *a, **k: None, raising=False)

    await recipes_mod.btn_puhlyash_recipe(_Msg(), state=None)

    assert seen.get("called") is True
    assert seen.get("profile") == {"cook_level": "beginner"}


# ── 3. meal_schedule_v2._fire: fitness gets the allowlist context ────────────


@pytest.mark.asyncio
async def test_meal_schedule_fire_feeds_fitness_context(tmp_db, monkeypatch):
    """Seam check: the closure is APScheduler-registered, so we verify
    (a) build_fitness_context returns exactly the allowlist from a real DB,
    (b) the _fire source wires fitness via build_fitness_context + context=."""
    import aiosqlite
    from planner.context import build_fitness_context

    async with aiosqlite.connect(tmp_db) as db:
        ctx = await build_fitness_context(db, "42")
    assert ctx == {"activity": "medium", "goal": "lose_weight"}

    src = (PROJ / "bot_handlers" / "meal_schedule_v2.py").read_text()
    assert "build_fitness_context" in src
    assert "context=fit_ctx" in src
