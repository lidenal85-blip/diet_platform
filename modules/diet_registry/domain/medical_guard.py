"""Medical Dictionary Guard — белый/чёрный список продуктов.

Layer 2 защиты от Data Poisoning (audit finding).
"""

# Опасные вещества / токсины в разрешённых продуктах
DANGEROUS_SUBSTANCES = {
    "мышьяк", "цианид", "арсен", "arsenic", "cyanide", "mercury",
    "ртуть", "свинец", "блекота", "метанол",
    "bleach", "detergent", "turpentine", "gasoline",
}

# Абсолютные противопоказания при диабете (образец)
DIABETES_FORBIDDEN = {
    "сахар", "сахароза", "фруктоза",
}

# Конфликты: заболевание -> продукты, недопустимые в allowed_foods
CRITICAL_CONFLICTS = {
    "диабет": DIABETES_FORBIDDEN,
    "diabetes": DIABETES_FORBIDDEN,
}


def check_dangerous_substances(foods: list) -> list:
    """Returns список опасных продуктов если найдены."""
    found = []
    for food in foods:
        food_lower = food.lower()
        for danger in DANGEROUS_SUBSTANCES:
            if danger in food_lower:
                found.append(food)
                break
    return found


def check_critical_conflicts(conditions: list, allowed_foods: list) -> list:
    """Returns конфликты: [продукт, заболевание]."""
    conflicts = []
    for condition in conditions:
        cond_lower = condition.lower()
        for disease_key, forbidden_set in CRITICAL_CONFLICTS.items():
            if disease_key in cond_lower:
                for food in allowed_foods:
                    if any(f in food.lower() for f in forbidden_set):
                        conflicts.append((food, condition))
    return conflicts


def validate_diet_draft(draft_data: dict) -> tuple[bool, list]:
    """
    Returns (is_valid, issues).
    Должна вернуть False если найдены опасные продукты или конфликты.
    """
    issues = []

    allowed = draft_data.get("allowed_foods", [])
    conditions = draft_data.get("conditions", [])
    diet_name = draft_data.get("diet_name", "")

    # Проверка опасных веществ
    dangerous = check_dangerous_substances(allowed)
    for d in dangerous:
        issues.append(f"DANGEROUS_SUBSTANCE_IN_ALLOWED: {d}")

    # Проверка критических конфликтов
    conflicts = check_critical_conflicts(conditions, allowed)
    for food, condition in conflicts:
        issues.append(f"CONFLICT: '{food}' allowed but condition is '{condition}'")

    # Проверка названия
    if not diet_name or len(diet_name.strip()) < 3:
        issues.append("INVALID_DIET_NAME")

    return len(issues) == 0, issues