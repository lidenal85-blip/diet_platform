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
    "breakfast": "утренняя офисная разминка до еды, 3-5 минут прямо за столом или рядом, без прыжков",
    "lunch":     "лёгкая растяжка после обеда, 5 минут, сидя или стоя рядом с рабочим местом",
    "dinner":    "вечерняя расслабляющая растяжка дома, 7-10 минут, без нагрузки",
}

DIET_HINTS = {
    "quick":      "лёгкая активация тела, 3-4 простых движения",
    "home":       "умеренная растяжка и дыхание",
    "restaurant": "после обильной еды: только ходьба и дыхание, никакого пресса",
    "pp":         "активация метаболизма: шаги на месте, вращения, наклоны",
}

SYS = """Ты фитнес-тренер, специализируешься на офисной и домашней микро-гимнастике.
Генерируй 3-4 лёгких упражнения:
- Можно делать в офисе или дома, без инвентаря и снарядов
- Без прыжков, рывков, тяжёлой нагрузки
- Подходит людям с разным уровнем подготовки
- Обязательно предупреди если есть ограничения (спина, суставы — делать осторожно)
Отвечай строго в JSON без текста вне JSON:
[{"name":"","description":"как делать, 1-2 предложения","reps":"","duration_sec":30,"caution":""}]"""

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
    lines = ["💪 <b>Разминка (<i>осторожно при проблемах со спиной или суставами</i>):</b>"]
    for i, ex in enumerate(exercises, 1):
        reps = ex.get("reps", "")
        dur = ex.get("duration_sec", "")
        timing = f"{reps}" if reps else f"{dur} сек"
        lines.append(f"{i}. <b>{ex['name']}</b> — {timing}")
        lines.append(f"   {ex.get('description', '')}")
        caution = ex.get("caution", "")
        if caution:
            lines.append(f"   ⚠️ {caution}")
    return "\n".join(lines)