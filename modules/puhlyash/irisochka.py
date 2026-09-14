"""Ирисочка — мышка-помощник Пухляша, диетолог и нутрициолог.

Персонаж: маленькая серая мышка в белом колпаке, умная и заботливая.
Тон: профессиональный, тёплый, иногда мягко поправляет Пухляша.
Назначение:
- Комментарии к рецептам (БЖУ, польза, нюансы)
- Советы по диете с медицинской точки зрения
- «Голос разума» когда Пухляш предлагает что-то жирное
"""
import json
import random
import sys
import logging

log = logging.getLogger(__name__)

sys.path.insert(0, "/opt/leviathan_engine")
try:
    from llm_factory import LLMFactory
    _LEVIATHAN_CORE = True
    log.info("🔗 Leviathan LLMFactory подключён в puhlyash/irisochka.py")
except ImportError:
    _LEVIATHAN_CORE = False
    log.warning("⚠️ LLMFactory недоступен в puhlyash/irisochka.py — советы Ирисочки требуют LLM")

SYS_IRISOCHKA = """Ты Ирисочка — маленькая серая мышка в белом поварском колпаке, помощник Пухляша и нутрициолог.
Твой характер:
- Умная, заботливая, профессиональная
- Иногда мягко поправляешь Пухляша (но никогда грубо)
- Говоришь коротко, дружелюбно, иногда с маленьким юмором
- Оперируешься фактами (ПжУ, витамины, минералы)
Отвечай 2-3 предложения. На русском. Начинай с "🐭 Ирисочка:"."""

# Комментарии по категориям рецептов
_QUICK_FACTS = [
    "🐭 Ирисочка: Не забывай выпивать стакан воды за 30 минут до еды — это помогает пищеварению!",
    "🐭 Ирисочка: Жуй медленнее — мозг получает сигнал насыщения через 20 минут!",
    "🐭 Ирисочка: Зелень лучше есть свежей — при тепловой обработке теряется до 50% витамина C.",
    "🐭 Ирисочка: Яйцо через день — отличный источник белка без проблем для сердца.",
    "🐭 Ирисочка: Добавь зелёнь в пасту не в конце варки, а прямо на тарелку — сохранишь цвет и витамины!",
    "🐭 Ирисочка: Кефир в маринаде — не только вкусно, но и пробиотики для кишечника.",
    "🐭 Ирисочка: Гречка — чемпион по белку среди круп, и Пухляш это знает!",
]


def get_quick_tip() -> str:
    """Случайный быстрый совет Ирисочки."""
    return random.choice(_QUICK_FACTS)


async def _gemini(prompt: str) -> str:
    """LLM-вызов через Leviathan LLMFactory (KeyPool + CircuitBreaker + Groq fallback)
    вместо raw urllib и ручной ротации ключей из чужого env-файла.
    """
    if not _LEVIATHAN_CORE:
        raise RuntimeError("LLMFactory недоступен")
    return await LLMFactory.execute_request(
        prompt=prompt,
        system=SYS_IRISOCHKA,
        model="gemini-3.1-flash-lite",
        driver="gemini",
        fallback=True,
        task_type="structured",
    )


async def comment_recipe(recipe: dict) -> str:
    """Ирисочка комментирует рецепт Gemini."""
    title = recipe.get("title", "?")
    kcal = recipe.get("calories_per_serving", "?")
    p = recipe.get("protein_g", "?")
    f = recipe.get("fat_g", "?")
    c = recipe.get("carbs_g", "?")
    try:
        ingr = json.loads(recipe.get("ingredients", "[]"))[:5]
    except Exception:
        ingr = []

    prompt = (
        f"Рецепт: {title}. "
        f"ПЖУ: белки {p}г, жиры {f}г, углеводы {c}г, {kcal} ккал. "
        f"Ингредиенты: {', '.join(ingr)}. "
        f"Дай короткий нутриционный комментарий и 1 совет по улучшению."
    )
    return await _gemini(prompt)


async def advise_diet(goal: str, restrictions: str = "") -> str:
    """Ирисочка даёт совет по диете."""
    prompt = f"Цель: {goal}. Ограничения: {restrictions or 'нет'}. Какой один важный нюанс должен знать человек?"
    return await _gemini(prompt)