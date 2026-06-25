"""Recipe Engine v2."""
import json, uuid, sys
sys.path.insert(0, "/opt/diet_platform")
sys.path.insert(0, "/opt/leviathan_engine")
from building_blocks.logger import get_logger
log = get_logger(__name__)

try:
    from llm_factory import LLMFactory
    _LEVIATHAN_CORE = True
    log.info("🔗 Leviathan LLMFactory подключён в recipes/engine.py")
except ImportError:
    _LEVIATHAN_CORE = False
    log.warning("⚠️ LLMFactory недоступен в recipes/engine.py")

MODES = {"quick": "⚡ Быстро", "home": "🏠 Домашний", "restaurant": "🍽 Ресторанный", "pp": "🥦 ПП"}

SYS_PROMPT = """Ты шеф-повар и диетолог. Отвечай строго в JSON без текста вне JSON.
{"title":"","description":"","mode":"","cook_time_minutes":0,"servings":2,
"calories_per_serving":0,"protein_g":0,"fat_g":0,"carbs_g":0,
"ingredients":["ингредиент - количество"],"steps":["Шаг 1: ..."],"tags":[]}"""

RECIPE_MODEL = "gemini-3.1-flash-lite"


async def _gemini(prompt: str) -> str:
    """LLM-вызов через Leviathan LLMFactory (KeyPool + CircuitBreaker + Groq fallback)
    вместо raw urllib + ручной ротации ключей из .env.
    """
    if not _LEVIATHAN_CORE:
        raise RuntimeError("LLMFactory недоступен")
    return await LLMFactory.execute_request(
        prompt=prompt,
        system=SYS_PROMPT,
        model=RECIPE_MODEL,
        driver="gemini",
        fallback=True,
        task_type="structured",
    )


def _parse(raw: str, mode: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    d = json.loads(raw)
    d["id"] = str(uuid.uuid4())
    d["mode"] = mode
    for field in ["ingredients", "steps", "tags"]:
        d[field] = json.dumps(d.get(field, []), ensure_ascii=False)
    return d


async def generate_recipe(query: str, mode: str, profile: dict | None = None) -> dict:
    from modules.recipes.prompt_builder import build_recipe_prompt
    prompt = build_recipe_prompt(query, mode, profile)
    raw = await _gemini(prompt)
    return _parse(raw, mode)


async def generate_from_fridge(ingredients: list) -> dict:
    prompt = f"Холодильник: {', '.join(ingredients)}. Что приготовить? Режим: home."
    raw = await _gemini(prompt)
    return _parse(raw, "home")


async def generate_budget_recipe(budget: int, currency: str = "руб") -> dict:
    prompt = f"Ужин для семьи на {budget} {currency}, доступные продукты. Режим: home."
    raw = await _gemini(prompt)
    return _parse(raw, "home")