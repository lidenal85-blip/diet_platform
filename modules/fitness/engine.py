"""Fitness Engine — лёгкие упражнения без снарядов через Gemini."""
import json, sys
sys.path.insert(0, "/opt/leviathan_engine")
from building_blocks.logger import get_logger

log = get_logger(__name__)

try:
    from llm_factory import LLMFactory
    _LEVIATHAN_CORE = True
    log.info("🔗 Leviathan LLMFactory подключён в fitness/engine.py")
except ImportError:
    _LEVIATHAN_CORE = False
    log.warning("⚠️ LLMFactory недоступен в fitness/engine.py")

MEAL_CONTEXT = {
    "breakfast": "утренная разминка до еды, 5-7 минут, лёгкая",
    "lunch": "после обеда 30 мин прогулка, потом лёгкая растяжка 5 мин",
    "dinner": "вечерняя растяжка и релаксация, 7-10 минут",
}

DIET_HINTS = {
    "quick": "быстрый метаболизм, лёгкое кардио",
    "home": "умеренная нагрузка, растяжка",
    "restaurant": "после обильной еды, лёгкая прогулка",
    "pp": "для похудения, кардио + растяжка",
}

SYS = """Ты фитнес-тренер. Генерируй 3-4 упражнения без снарядов и без инвентаря. Отвечай строго в JSON.
[{"name":"","description":"как делать, 1-2 предложения","reps":"","duration_sec":30}]"""

FITNESS_MODEL = "gemini-3.1-flash-lite"


async def _gemini(prompt: str) -> str:
    """LLM-вызов через Leviathan LLMFactory (KeyPool + CircuitBreaker + Groq fallback)
    вместо raw urllib + ручной ротации ключей из .env.
    """
    if not _LEVIATHAN_CORE:
        raise RuntimeError("LLMFactory недоступен")
    return await LLMFactory.execute_request(
        prompt=prompt,
        system=SYS,
        model=FITNESS_MODEL,
        driver="gemini",
        fallback=True,
        task_type="structured",
    )


def _parse(raw: str) -> list:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(raw)


async def generate_exercises(meal: str, diet_mode: str = "home") -> list:
    ctx = MEAL_CONTEXT.get(meal, "лёгкая разминка")
    hint = DIET_HINTS.get(diet_mode, "")
    prompt = f"Контекст: {ctx}. Диета: {hint}. Без инвентаря, без снарядов."
    raw = await _gemini(prompt)
    return _parse(raw)


def format_exercises(exercises: list) -> str:
    lines = ["💪 <b>Упражнения:</b>"]
    for i, ex in enumerate(exercises, 1):
        reps = ex.get("reps", "")
        dur = ex.get("duration_sec", "")
        timing = f"{reps}" if reps else f"{dur} сек"
        lines.append(f"{i}. <b>{ex['name']}</b> — {timing}")
        lines.append(f"   {ex.get('description', '')}")
    return "\n".join(lines)