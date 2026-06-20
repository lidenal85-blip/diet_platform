"""\u041f\u0443\u0445\u043b\u044f\u0448 \u2014 \u043f\u0435\u0440\u0441\u043e\u043d\u0430\u0436 \u0438 \u0435\u0433\u043e \u0440\u0435\u0446\u0435\u043f\u0442\u044b \u0441 \u0445\u0430\u0440\u0430\u043a\u0442\u0435\u0440\u043e\u043c."""
import json
import random
import re
from datetime import datetime

# \u0424\u0440\u0430\u0437\u044b \u043f\u043e \u0432\u0440\u0435\u043c\u0435\u043d\u0438 \u0441\u0443\u0442\u043e\u043a
TIME_VIBES = {
    "morning": [
        "\u0423\u0442\u0440\u043e \u0434\u043e\u0431\u0440\u043e\u0435! \u041f\u0443\u0445\u043b\u044f\u0448 \u0443\u0436\u0435 \u043d\u0430 \u043a\u0443\u0445\u043d\u0435 \u2014 \u0445\u043e\u0447\u0435\u0442\u0441\u044f \u0447\u0435\u0433\u043e-\u0442\u043e \u0441\u044a\u0435\u0441\u0442\u044c!",
        "\u0429\u0451\u043b\u043a, \u0432\u0441\u0442\u0430\u0432\u0430\u0442\u044c \u0443\u0436\u0435 \u043f\u043e\u0440\u0430 \u2014 \u0437\u0430\u0442\u043e \u0437\u0430\u0432\u0442\u0440\u0430\u043a \u0431\u0443\u0434\u0435\u0442 \u043f\u043e\u043c\u043e\u0433\u0430\u0442\u044c!",
        "\u0414\u043e\u0431\u0440\u043e\u0435 \u0443\u0442\u0440\u043e! \u041d\u0430\u043a\u043e\u0440\u043c\u0438\u043c \u0442\u0435\u0431\u044f \u043f\u0435\u0440\u0435\u0434 \u0434\u043d\u0451\u043c.",
    ],
    "lunch": [
        "\u041f\u043e\u043b\u0434\u0435\u043d\u044c! \u0416\u0435\u043b\u0443\u0434\u043e\u043a \u0443\u0436\u0435 \u043d\u0430\u043c\u0435\u043a\u0430\u0435\u0442 \u2014 \u043f\u043e\u0440\u0430 \u043f\u043e\u0435\u0441\u0442\u044c \u043f\u043e-\u043d\u043e\u0432\u043e\u043c\u0443!",
        "\u041e\u0431\u0435\u0434 \u043d\u0435 \u0437\u0430 \u0433\u043e\u0440\u0430\u043c\u0438 \u2014 \u041f\u0443\u0445\u043b\u044f\u0448 \u0443\u0436\u0435 \u043f\u0440\u0438\u0434\u0443\u043c\u0430\u043b!",
        "\u0412 \u043f\u043e\u043b\u0434\u0435\u043d\u044c \u043d\u0430\u0434\u043e \u043a\u0443\u0448\u0430\u0442\u044c \u0442\u0430\u043a, \u0447\u0442\u043e\u0431 \u0434\u043e \u0432\u0435\u0447\u0435\u0440\u0430 \u0445\u0432\u0430\u0442\u0430\u043b\u043e!",
    ],
    "dinner": [
        "\u0412\u0435\u0447\u0435\u0440 — \u0432\u0440\u0435\u043c\u044f \u043d\u0430\u043a\u043e\u0440\u043c\u0438\u0442\u044c \u0441\u0435\u0431\u044f \u0437\u0430 \u0434\u0435\u043d\u044c!",
        "\u0423\u0436\u0438\u043d \u043d\u0435 \u0437\u0430 \u0433\u043e\u0440\u0430\u043c\u0438 \u2014 \u041f\u0443\u0445\u043b\u044f\u0448 \u0437\u043d\u0430\u0435\u0442 \u0447\u0442\u043e \u043f\u0440\u0438\u0433\u043e\u0442\u043e\u0432\u0438\u0442\u044c!",
        "\u0415\u0449\u0451 \u0434\u0435\u043d\u044c \u043f\u043e\u0437\u0430\u0434\u0438, \u0430 \u0432\u0435\u0447\u0435\u0440\u043e\u043c \u0432\u043a\u0443\u0441\u043d\u043e \u043f\u043e\u0435\u0441\u0442\u044c — \u0437\u0430\u0441\u043b\u0443\u0436\u0438\u043b!",
    ],
    "night": [
        "\u041f\u043e\u0437\u0434\u043d\u043e, \u043d\u043e \u041f\u0443\u0445\u043b\u044f\u0448 \u043d\u0435 \u0441\u043f\u0438\u0442 \u2014 \u0434\u0430\u0432\u0430\u0439 \u044f\u0441\u043d\u044b\u0439 \u043f\u0435\u0440\u0435\u043a\u0443\u0441.",
        "\u041d\u043e\u0447\u044c, \u0430 \u0445\u043e\u0447\u0435\u0442\u0441\u044f \u2014 \u0437\u043d\u0430\u0435\u043c \u044d\u0442\u043e \u0447\u0443\u0432\u0441\u0442\u0432\u043e!",
    ],
}

# \u0421\u0435\u0437\u043e\u043d\u043d\u044b\u0435 / \u043f\u043e\u0433\u043e\u0434\u043d\u044b\u0435 \u043d\u0430\u0441\u0442\u0440\u043e\u0435\u043d\u0438\u044f
SEASON_VIBES = [
    "\u0416\u0430\u0440\u043a\u043e! \u041f\u043e\u0442\u044f\u043d\u0443\u043b\u043e \u043d\u0430 \u0447\u0442\u043e-\u0442\u043e \u043b\u0451\u0433\u043a\u043e\u0435 \u0438 \u043e\u0441\u0432\u0435\u0436\u0430\u044e\u0449\u0435\u0435.",
    "\u041b\u0435\u0442\u043e \u0432 \u0440\u0430\u0437\u0433\u0430\u0440\u0435 \u2014 \u0437\u043d\u0430\u0447\u0438\u0442 \u043f\u043e\u0440\u0430 \u0433\u043e\u0442\u043e\u0432\u0438\u0442\u044c \u0447\u0442\u043e-\u0442\u043e \u0441 \u043e\u0433\u043e\u0440\u043e\u0434\u0430.",
    "\u0416\u0430\u0440\u0430 \u0442\u0430\u043a\u0430\u044f, \u0447\u0442\u043e \u0445\u043e\u0447\u0435\u0442\u0441\u044f \u043e\u043a\u0440\u043e\u0448\u043a\u0438 \u0438 \u0445\u043e\u043b\u043e\u0434\u043d\u043e\u0433\u043e п\u0438\u0432\u0430.",
    "\u0413\u043e\u0440\u044f\u0447\u0435\u0435 \u043b\u0435\u0442\u043e \u2014 \u0441\u0430\u043c\u043e\u0435 \u0432\u0440\u0435\u043c\u044f \u0434\u043b\u044f \u043b\u0451\u0433\u043a\u0438\u0445 \u0441\u0430\u043b\u0430\u0442\u043e\u0432 \u0438 \u043e\u043a\u0440\u043e\u0448\u0435\u043a.",
]

# \u0421\u043f\u043e\u043d\u0442\u0430\u043d\u043d\u044b\u0435 \u043d\u0430\u0441\u0442\u0440\u043e\u0435\u043d\u0438\u044f \u041f\u0443\u0445\u043b\u044f\u0448\u0430

SYS_PUHLYASH = """Ты Пухляш — обычный парень, который очень любит поесть вкусно.
Твои рецепты: из простых обычных продуктов из любого супермаркета,
иногда с одной неожиданной деталью, без пармезана и трюфелей.
Отвечай строго в JSON без текста вне JSON:
{"title":"","description":"","mode":"home","cook_time_minutes":0,"servings":2,
"calories_per_serving":0,"protein_g":0,"fat_g":0,"carbs_g":0,
"ingredients":[],"steps":[],"tags":[]}"""

MOOD_PROMPTS = {
    "sweet":   "Сладкий десерт, построще. Не торт с зеркалами.",
    "comfort": "Сытное домашнее — картошка, гречка, макароны или пильмень.",
    "light":   "Лёгкий салат или закуска — ничего тяжёлого.",
    "spicy":   "Что-то острое, с перцем или чили.",
    "quick":   "На скорую руку, готовится за 10-15 минут.",
    "classic": "Проверенная классика которую все знают.",
    "summer":  "Летнее — окрошка, салат с огорода, газпачо.",
    "special": "Обычное блюдо с одной интересной деталью которая всё меняет.",
}

MOOD_TRIGGERS = [
    ("sweet", "\u0427\u0442\u043e-\u0442\u043e \u043f\u043e\u0442\u044f\u043d\u0443\u043b\u043e \u043d\u0430 \u0441\u043b\u0430\u0434\u043a\u043e\u0435, \u043f\u043e\u044d\u0442\u043e\u043c\u0443 \u0440\u0435\u0448\u0438\u043b \u043f\u0440\u0438\u0433\u043e\u0442\u043e\u0432\u0438\u0442\u044c \u0432\u0430\u043c —"),
    ("comfort", "\u0412\u0435\u0447\u0435\u0440 \u0442\u0430\u043a\u043e\u0439, \u0447\u0442\u043e \u0445\u043e\u0447\u0435\u0442\u0441\u044f \u0447\u0435\u0433\u043e-\u0442\u043e \u0434\u043e\u043c\u0430\u0448\u043d\u0435\u0433\u043e \u0438 \u0441\u044b\u0442\u043d\u043e\u0433\u043e:"),
    ("light", "\u041a\u0430\u043a-\u0442\u043e \u043b\u0435\u0433\u043a\u043e \u0441\u0442\u0430\u043b\u043e, \u043f\u043e\u044d\u0442\u043e\u043c\u0443 \u0441\u0435\u0433\u043e\u0434\u043d\u044f \u0447\u0442\u043e-\u0442\u043e л\u0451\u0433\u043a\u043e\u0435:"),
    ("spicy", "\u0425\u043e\u0447\u0435\u0442\u0441\u044f \u043e\u0441\u0442\u0440\u043e\u0433\u043e! \u0414\u0443\u043c\u0430\u044e, \u0432\u044b \u043c\u0435\u043d\u044f \u043f\u043e\u0439\u043c\u0451\u0442\u0435 \u2014"),
    ("quick", "\u041d\u0435\u043a\u043e\u0433\u0434\u0430 \u043d\u0435 \u0445\u043e\u0447\u0435\u0442\u0441\u044f \u0441\u0442\u043e\u044f\u0442\u044c \u0434\u043e\u043b\u0433\u043e \u0443 п\u043b\u0438\u0442\u044b, \u043f\u043e\u044d\u0442\u043e\u043c\u0443 \u0431\u044b\u0441\u0442\u0440\u043e:"),
    ("classic", "\u0418\u043d\u043e\u0433\u0434\u0430 \u043b\u0443\u0447\u0448\u0435 п\u0440\u043e\u0432\u0435\u0440\u0435\u043d\u043d\u043e\u0435, \u0447\u0435\u043c \u043c\u043e\u0434\u043d\u043e\u0435. \u0421\u0435\u0433\u043e\u0434\u043d\u044f:"),
    ("summer", "\u0416\u0430\u0440\u043a\u043e, \u0445\u043e\u0447\u0435\u0442\u0441\u044f \u043e\u043a\u0440\u043e\u0448\u043a\u0438. \u041d\u0443 \u0438 \u043a\u0430\u043a \u0436\u0435 \u041f\u0443\u0445\u043b\u044f\u0448 \u0431\u0435\u0437 \u0441\u043b\u0430\u0434\u043a\u043e\u0433\u043e. \u041d\u0430 \u0434\u0435\u0441\u0435\u0440\u0442 —"),
]


def get_time_period() -> str:
    h = datetime.now().hour
    if 6 <= h < 11: return "morning"
    if 11 <= h < 15: return "lunch"
    if 15 <= h < 21: return "dinner"
    return "night"


def get_puhlyash_intro(mood: str | None = None) -> str:
    """\u0413\u0435\u043d\u0435\u0440\u0438\u0440\u0443\u0435\u0442 \u0432\u0441\u0442\u0443\u043f\u043b\u0435\u043d\u0438\u0435 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f \u043e\u0442 \u041f\u0443\u0445\u043b\u044f\u0448\u0430."""
    period = get_time_period()
    month = datetime.now().month

    # \u041b\u0435\u0442\u043e \u2014 \u0431\u043e\u043b\u044c\u0448\u0435 \u0448\u0430\u043d\u0441 н\u0430 \u043b\u0435\u0442\u043d\u0438\u0435 \u043d\u0430\u0441\u0442\u0440\u043e\u0435\u043d\u0438\u044f
    is_summer = month in (6, 7, 8)

    parts = []

    # \u0412\u0440\u0435\u043c\u0435\u043d\u043d\u043e\u0435 \u043f\u0440\u0438\u0432\u0435\u0442
    parts.append(random.choice(TIME_VIBES.get(period, TIME_VIBES["morning"])))

    # \u0421\u0435\u0437\u043e\u043d\u043d\u044b\u0439 \u0442\u0440\u0438\u0433\u0433\u0435\u0440 (\u0441 \u0432\u0435\u0440\u043e\u044f\u0442н. 60% \u043b\u0435\u0442\u043e\u043c)
    if is_summer and random.random() < 0.6:
        parts.append(random.choice(SEASON_VIBES))
    
    # \u041d\u0430\u0441\u0442\u0440\u043e\u0435\u043d\u0438\u0435 \u041f\u0443\u0445\u043b\u044f\u0448\u0430
    if mood:
        trigger = next((t for k, t in MOOD_TRIGGERS if k == mood), None)
        if trigger:
            parts.append(trigger)
    elif random.random() < 0.5:
        parts.append(random.choice(MOOD_TRIGGERS)[1])

    return " ".join(parts)


async def generate_puhlyash_recipe(profile: dict | None = None,
                                    diet_name: str | None = None,
                                    mood: str | None = None) -> dict:
    """Генерирует рецепт Пухляша — независимо от бюджета."""
    import asyncio, json, re as _re, urllib.request
    from modules.recipes.engine import _parse

    month = datetime.now().month
    is_summer = month in (6, 7, 8)

    if not mood:
        if is_summer:
            mood = random.choice(["summer", "light", "sweet", "special", None, None])
        else:
            mood = random.choice(["comfort", "classic", "sweet", "special", None, None])

    if diet_name:
        query = f"рецепт для диеты ‘{diet_name}’. Из доступных продуктов."
    elif mood and mood in MOOD_PROMPTS:
        query = MOOD_PROMPTS[mood]
    else:
        season = "лето" if is_summer else "осень" if month in (9,10,11) else "зима" if month in (12,1,2) else "весна"
        query = f"Вкусное блюдо на {season}. Простые ингредиенты, но с характером."

    # Вызываем Gemini с промптом Пухляша (без profile)
    env = open("/opt/leviathan_engine/agent_service/.env").read()
    keys = _re.findall(r"GEMINI_K\d+=([^\s]+)", env)
    random.shuffle(keys)
    raw = None
    for key in keys:
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"gemini-3.1-flash-lite:generateContent?key={key}")
        body = json.dumps({
            "system_instruction": {"parts": [{"text": SYS_PUHLYASH}]},
            "contents": [{"role": "user", "parts": [{"text": query}]}],
            "generationConfig": {"temperature": 0.9, "maxOutputTokens": 2048}
        }).encode()
        try:
            req = urllib.request.Request(url, body, {"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = json.loads(r.read())["candidates"][0]["content"]["parts"][0]["text"]
            break
        except Exception as e:
            if any(x in str(e) for x in ["403", "429", "503"]):
                continue
            raise
    if raw is None:
        raise RuntimeError("Gemini недоступен")

    recipe = _parse(raw, "home")
    recipe["puhlyash_intro"] = get_puhlyash_intro(mood)
    recipe["mood"] = mood
    return recipe


def format_puhlyash_message(recipe: dict) -> str:
    """\u0424\u043e\u0440\u043c\u0430\u0442\u0438\u0440\u0443\u0435\u0442 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435 \u0440\u0435\u0446\u0435\u043f\u0442\u0430 \u0434\u043d\u044f \u0441 \u0445\u0430\u0440\u0430\u043a\u0442\u0435\u0440\u043e\u043c."""
    import json as _json
    intro = recipe.get("puhlyash_intro", "")
    title = recipe.get("title", "?")
    desc = recipe.get("description", "")
    try:
        ingr = _json.loads(recipe.get("ingredients", "[]"))
        steps = _json.loads(recipe.get("steps", "[]"))
    except:
        ingr, steps = [], []
    kcal = recipe.get("calories_per_serving", "?")
    time = recipe.get("cook_time_minutes", "?")
    servings = recipe.get("servings", 2)

    lines = [
        f"\U0001f35d <b>\u0420\u0435\u0446\u0435\u043f\u0442 \u0434\u043d\u044f \u043e\u0442 \u041f\u0443\u0445\u043b\u044f\u0448\u0430</b>",
        "",
        f"\U0001f4ac <i>{intro}</i>",
        "",
        f"\u2728 <b>{title}</b>",
    ]
    if desc:
        lines.append(f"<i>{desc}</i>")
    lines += [
        "",
        f"\u23f1 {time} \u043c\u0438\u043d  |  \U0001f525 {kcal} \u043a\u043a\u0430\u043b  |  \U0001f464 {servings} \u043f\u043e\u0440\u0446",
        "",
        "<b>\u041d\u0430\u0434\u043e:</b>",
    ]
    for i in ingr:
        lines.append(f"\u2022 {i}")
    lines += ["", "<b>\u0413\u043e\u0442\u043e\u0432\u0438\u043c:</b>"]
    for s in steps:
        lines.append(s)
    return "\n".join(lines)