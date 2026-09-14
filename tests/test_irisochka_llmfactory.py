"""§20 step 5 — Irisochka → LLMFactory (security swap).

What the tests pin down:
1. No raw urllib LLM path and no foreign .env read
   (/opt/leviathan_engine/agent_service/) remain in the module.
2. LLM calls go through LLMFactory.execute_request with the established
   driver/model/fallback contract (same as recipes/engine.py).
3. Public signatures preserved: comment_recipe(recipe) -> str,
   advise_diet(goal, restrictions="") -> str, get_quick_tip() -> str.
4. LLM-unavailable behavior: RuntimeError (loud, no silent fallback text
   from _QUICK_FACTS on the LLM path — that fallback was masking errors).
"""
import ast
import json
import sys
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ))

IRISOCHKA = PROJ / "modules" / "puhlyash" / "irisochka.py"


# ── 1. static: no urllib, no foreign .env read ──────────────────────────────


def test_no_urllib_and_no_foreign_env_read():
    tree = ast.parse(IRISOCHKA.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        assert not isinstance(node, ast.Import) or not any(
            a.name.startswith("urllib") for a in node.names
        ), "raw urllib import found — raw LLM path must be gone"
        if isinstance(node, ast.ImportFrom):
            assert node.module != "urllib.request", "raw urllib import found"
    src = IRISOCHKA.read_text(encoding="utf-8")
    assert ".env" not in src, (
        "foreign .env file must not be read by irisochka"
    )
    assert "GEMINI_K" not in src, "manual key-pool regex must be gone"


# ── 2. LLM calls go through LLMFactory ──────────────────────────────────────


@pytest.fixture()
def factory_env(monkeypatch):
    """Fake LLMFactory + forced _LEVIATHAN_CORE (real import unavailable locally)."""
    import modules.puhlyash.irisochka as iri

    calls = {}

    class FakeFactory:
        @staticmethod
        async def execute_request(**kwargs):
            calls.update(kwargs)
            return "🐭 Ирисочка: Ответ фабрики."

    monkeypatch.setattr(iri, "LLMFactory", FakeFactory, raising=False)
    monkeypatch.setattr(iri, "_LEVIATHAN_CORE", True, raising=False)
    return calls


@pytest.mark.asyncio
async def test_comment_recipe_uses_llmfactory(factory_env):
    import modules.puhlyash.irisochka as iri

    out = await iri.comment_recipe(
        {"title": "Овсянка", "calories_per_serving": 250,
         "protein_g": 10, "fat_g": 5, "carbs_g": 40,
         "ingredients": '["овсянка", "молоко"]'}
    )

    assert out == "🐭 Ирисочка: Ответ фабрики."
    assert factory_env["driver"] == "gemini"
    assert factory_env["model"] == "gemini-3.1-flash-lite"
    assert factory_env["fallback"] is True
    assert factory_env["system"] == iri.SYS_IRISOCHKA
    assert "Овсянка" in factory_env["prompt"]
    assert "белки 10г" in factory_env["prompt"]


@pytest.mark.asyncio
async def test_advise_diet_signature_and_prompt(factory_env):
    import modules.puhlyash.irisochka as iri

    out = await iri.advise_diet("похудение", restrictions="без свинины")
    assert out == "🐭 Ирисочка: Ответ фабрики."
    assert "Цель: похудение" in factory_env["prompt"]
    assert "без свинины" in factory_env["prompt"]

    # default restrictions: "нет"
    await iri.advise_diet("набор массы")
    assert "Ограничения: нет" in factory_env["prompt"]


@pytest.mark.asyncio
async def test_llm_unavailable_raises_loudly(monkeypatch):
    """No silent _QUICK_FACTS fallback masking LLM errors on the LLM path."""
    import modules.puhlyash.irisochka as iri

    monkeypatch.setattr(iri, "_LEVIATHAN_CORE", False, raising=False)

    with pytest.raises(RuntimeError):
        await iri.comment_recipe({"title": "X"})


def test_get_quick_tip_still_works():
    from modules.puhlyash.irisochka import get_quick_tip

    tip = get_quick_tip()
    assert tip.startswith("🐭 Ирисочка:")
