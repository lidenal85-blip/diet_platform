"""Recipe Engine v2."""
import json, uuid, sys, re, random
sys.path.insert(0, "/opt/diet_platform")
from building_blocks.logger import get_logger
log = get_logger(__name__)

MODES = {"quick": "⚡ Быстро", "home": "🏠 Домашний", "restaurant": "🍽 Ресторанный", "pp": "🥦 ПП"}

SYS_PROMPT = """Ты шеф-повар и диетолог. Отвечай строго в JSON без текста вне JSON.
{"title":"","description":"","mode":"","cook_time_minutes":0,"servings":2,
"calories_per_serving":0,"protein_g":0,"fat_g":0,"carbs_g":0,
"ingredients":["ингредиент - количество"],"steps":["Шаг 1: ..."],"tags":[]}"""


def _gemini(prompt: str) -> str:
    import urllib.request
    env = open("/opt/leviathan_engine/agent_service/.env").read()
    keys = re.findall(r'GEMINI_K\d+=([^\s]+)', env)
    random.shuffle(keys)
    for key in keys:
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"gemini-3.1-flash-lite:generateContent?key={key}")
        body = json.dumps({
            "system_instruction": {"parts": [{"text": SYS_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2048}
        }).encode()
        try:
            req = urllib.request.Request(
                url, body, {"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            if any(x in str(e) for x in ["403", "429", "503"]):
                continue
            raise
    raise RuntimeError("Gemini: все ключи исчерпаны")


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
    import asyncio
    from modules.recipes.prompt_builder import build_recipe_prompt
    prompt = build_recipe_prompt(query, mode, profile)
    raw = await asyncio.get_running_loop().run_in_executor(None, _gemini, prompt)
    return _parse(raw, mode)


async def generate_from_fridge(ingredients: list) -> dict:
    import asyncio
    prompt = f"Холодильник: {', '.join(ingredients)}. Что приготовить? Режим: home."
    raw = await asyncio.get_running_loop().run_in_executor(None, _gemini, prompt)
    return _parse(raw, "home")


async def generate_budget_recipe(budget: int, currency: str = "руб") -> dict:
    import asyncio
    prompt = f"Ужин для семьи на {budget} {currency}, доступные продукты. Режим: home."
    raw = await asyncio.get_running_loop().run_in_executor(None, _gemini, prompt)
    return _parse(raw, "home")