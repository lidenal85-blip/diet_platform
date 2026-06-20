"""Profile-aware recipe prompt builder."""

COOK_LEVEL_HINTS = {
    "beginner":  "уровень новичок: максимум 3-4 шага, минимум ингредиентов, никаких сложных техник. Яичница, пельмени, паста с маслом.",
    "amateur":   "уровень любитель: до 6 шагов, знакомые продукты, простые соусы. Омлет, суп, паста болоньезе.",
    "cook":      "уровень уверенный: любое число шагов, можно мариновать, тушить, запекать.",
    "expert":    "уровень эксперт: равиоли, ризотто, сложные соусы, профессиональные техники.",
}

BUDGET_HINTS = {
    "student": "бюджет студент: дешёвые доступные продукты, никаких деликатесов и пармезанов.",
    "normal":  "обычный бюджет: обычные продукты из супермаркета.",
    "free":    "бюджет не ограничен: можно дорогие ингредиенты.",
}

EXPERIMENT_HINTS = {
    "classic":    "только проверенные блюда, ничего необычного.",
    "sometimes": "иногда можно что-то новое, но не каждый раз.",
    "explorer":  "люблю пробовать новое, необычные сочетания приветствуются.",
}

TIME_HINTS = {
    15: "максимум 15 минут на приготовление.",
    30: "максимум 30 минут.",
    60: "время не ограничено.",
}


def build_recipe_prompt(query: str, mode: str, profile: dict | None = None) -> str:
    hints = {
        "quick":      "15-20 мин, минимум ингредиентов",
        "home":       "домашняя кухня, доступные продукты",
        "restaurant": "ресторанная подача",
        "pp":         "низкокалорийный, без сахара",
    }.get(mode, "")

    lines = [f"Режим '{mode}' ({hints}): {query}"]

    if profile:
        lvl = profile.get("cook_level", "beginner")
        bud = profile.get("budget_level", "normal")
        exp = profile.get("experiment_level", "sometimes")
        tme = profile.get("max_cook_time", 30)
        excl = profile.get("excluded_foods", "[]")

        lines.append(f"\nТребования пользователя:")
        lines.append(f"- {COOK_LEVEL_HINTS.get(lvl, '')}")
        lines.append(f"- {BUDGET_HINTS.get(bud, '')}")
        lines.append(f"- {EXPERIMENT_HINTS.get(exp, '')}")
        lines.append(f"- {TIME_HINTS.get(tme, str(tme) + ' мин')}")
        if excl and excl != "[]":
            lines.append(f"- Исключить: {excl}")

        lines.append("\nВАЖНО: рецепт должен строго соответствовать уровню. "
                       "Новичку НЕ давать равиоли и пармезан. "
                       "Студенту НЕ давать дорогие ингредиенты.")

    return "\n".join(lines)


def build_random_recipe_prompt(profile: dict | None = None, diet_name: str | None = None) -> str:
    if diet_name:
        return f"Случайный рецепт для диеты '{diet_name}'. Режим: home."

    lvl = (profile or {}).get("cook_level", "beginner")
    bud = (profile or {}).get("budget_level", "normal")
    lines = [
        "Случайный рецепт на сегодня. Режим: home.",
        f"- {COOK_LEVEL_HINTS.get(lvl, '')}",
        f"- {BUDGET_HINTS.get(bud, '')}",
        "Сделай рецепт простым, понятным, вкусным.",
    ]
    return "\n".join(lines)