"""Пухляш — персонаж и его рецепты с характером."""
import json
import random
import sys
from datetime import datetime
from building_blocks.logger import get_logger

log = get_logger(__name__)

sys.path.insert(0, "/opt/leviathan_engine")
try:
    from llm_factory import LLMFactory
    _LEVIATHAN_CORE = True
except ImportError:
    _LEVIATHAN_CORE = False
    log.warning("LLMFactory недоступен в puhlyash/persona.py")

# Фразы по времени суток
TIME_VIBES = {
    "morning": [
        "Утро доброе! Пухляш уже на кухне — хочется чего-то съесть!",
        "Щёлк, вставать уже пора — зато завтрак будет помогать!",
        "Доброе утро! Накормим тебя перед днём.",
    ],
    "lunch": [
        "Полдень! Желудок уже намекает — пора поесть по-новому!",
        "Обед не за горами — Пухляш уже придумал!",
        "В полдень надо кушать так, чтоб до вечера хватало!",
    ],
    "dinner": [
        "Вечер — время накормить себя за день!",
        "Ужин не за горами — Пухляш знает что приготовить!",
        "Ещё день позади, а вечером вкусно поесть — заслужил!",
    ],
    "night": [
        "Поздно, но Пухляш не спит — давай ясный перекус.",
        "Ночь, а хочется — знаем это чувство!",
    ],
}

# Сезонные / погодные настроения
SEASON_VIBES = [
    "Жарко! Потянуло на что-то лёгкое и освежающее.",
    "Лето в разгаре — значит пора готовить что-то с огорода.",
    "Жара такая, что хочется окрошки и холодного пива.",
    "Горячее лето — самое время для лёгких салатов и окрошек.",
]

# Спонтанные настроения Пухляша

SYS_PUHLYASH = """Ты Пухляш — рыжий кот в фартуке, обычный парень который очень любит поесть вкусно.
Твои рецепты: из простых обычных продуктов из любого супермаркета,
иногда с одной неожиданной деталью, без пармезана и трюфелей.
Тон: дружелюбный, лёгкая самоирония, не подкалываешься — но никогда не грубишь.
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
    ("sweet", "Что-то потянуло на сладкое, поэтому решил приготовить вам —"),
    ("comfort", "Вечер такой, что хочется чего-то домашнего и сытного:"),
    ("light", "Как-то легко стало, поэтому сегодня что-то лёгкое:"),
    ("spicy", "Хочется острого! Думаю, вы меня поймёте —"),
    ("quick", "Некогда не хочется стоять долго у плиты, поэтому быстро:"),
    ("classic", "Иногда лучше проверенное, чем модное. Сегодня:"),
    ("summer", "Жарко, хочется окрошки. Ну и как же Пухляш без сладкого. На десерт —"),
]


def get_time_period() -> str:
    h = datetime.now().hour
    if 6 <= h < 11: return "morning"
    if 11 <= h < 15: return "lunch"
    if 15 <= h < 21: return "dinner"
    return "night"


def get_puhlyash_intro(mood: str | None = None) -> str:
    """Генерирует вступление сообщения от Пухляша."""
    period = get_time_period()
    month = datetime.now().month

    # Лето — больше шанс на летние настроения
    is_summer = month in (6, 7, 8)

    parts = []

    # Временное привет
    parts.append(random.choice(TIME_VIBES.get(period, TIME_VIBES["morning"])))

    # Сезонный триггер (с вероятн. 60% летом)
    if is_summer and random.random() < 0.6:
        parts.append(random.choice(SEASON_VIBES))
    
    # Настроение Пухляша
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

    # LLMFactory (KeyPool + CircuitBreaker + Groq fallback) -- замена urllib
    if not _LEVIATHAN_CORE:
        raise RuntimeError("LLMFactory недоступен")
    raw = await LLMFactory.execute_request(
        prompt=query,
        system=SYS_PUHLYASH,
        model="gemini-3.1-flash-lite",
        driver="gemini",
        fallback=True,
        task_type="structured",
    )

    recipe = _parse(raw, "home")
    recipe["puhlyash_intro"] = get_puhlyash_intro(mood)
    recipe["mood"] = mood
    return recipe


def format_puhlyash_message(recipe: dict, irisochka_tip: str = "") -> str:
    """Форматирует сообщение рецепта дня с характером."""
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
        f"\U0001f35d <b>Рецепт дня от Пухляша</b>",
        "",
        f"\U0001f4ac <i>{intro}</i>",
        "",
        f"✨ <b>{title}</b>",
    ]
    if desc:
        lines.append(f"<i>{desc}</i>")
    lines += [
        "",
        f"⏱ {time} мин  |  \U0001f525 {kcal} ккал  |  \U0001f464 {servings} порц",
        "",
        "<b>Надо:</b>",
    ]
    for i in ingr:
        lines.append(f"• {i}")
    lines += ["", "<b>Готовим:</b>"]
    for s in steps:
        lines.append(s)
    # Ирисочка — нутриционный коммент
    tip = irisochka_tip or recipe.get("irisochka_tip", "")
    if not tip:
        from modules.puhlyash.irisochka import get_quick_tip
        tip = get_quick_tip()
    lines += ["", tip]
    return "\n".join(lines)
