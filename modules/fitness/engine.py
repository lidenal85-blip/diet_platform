"""Fitness Engine — лёгкие упражнения без снарядов через Gemini."""
import json, re, random
import urllib.request
from building_blocks.logger import get_logger

log = get_logger(__name__)

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


def _gemini(prompt: str) -> str:
    env = open("/opt/leviathan_engine/agent_service/.env").read()
    keys = re.findall(r'GEMINI_K\d+=([^\s]+)', env)
    random.shuffle(keys)
    for key in keys:
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"gemini-3.1-flash-lite:generateContent?key={key}")
        body = json.dumps({
            "system_instruction": {"parts": [{"text": SYS}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 800}
        }).encode()
        try:
            req = urllib.request.Request(
                url, body, {"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            if any(x in str(e) for x in ["403", "429", "503"]):
                continue
            raise
    raise RuntimeError("Gemini недоступен")


def _parse(raw: str) -> list:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(raw)


async def generate_exercises(meal: str, diet_mode: str = "home") -> list:
    import asyncio
    ctx = MEAL_CONTEXT.get(meal, "лёгкая разминка")
    hint = DIET_HINTS.get(diet_mode, "")
    prompt = f"Контекст: {ctx}. Диета: {hint}. Без инвентаря, без снарядов."
    raw = await asyncio.get_running_loop().run_in_executor(None, _gemini, prompt)
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