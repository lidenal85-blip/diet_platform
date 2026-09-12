"""Тесты модуля Пухляш (persona + irisochka)."""
import pytest
import json
from datetime import datetime


# ── Persona tests ──

class TestTimePeriod:
    """get_time_period() — временные периоды."""

    def test_morning(self):
        from modules.puhlyash.persona import get_time_period
        period = get_time_period()
        assert period in ("morning", "lunch", "dinner", "night"), (
            f"get_time_period() вернул '{period}', ожидается morning/lunch/dinner/night"
        )

    def test_season_vibes_not_empty(self):
        from modules.puhlyash.persona import SEASON_VIBES
        assert len(SEASON_VIBES) >= 3

    def test_time_vibes_all_periods(self):
        from modules.puhlyash.persona import TIME_VIBES
        for period in ("morning", "lunch", "dinner", "night"):
            assert period in TIME_VIBES
            assert len(TIME_VIBES[period]) >= 1

    def test_mood_triggers_exist(self):
        from modules.puhlyash.persona import MOOD_TRIGGERS
        assert len(MOOD_TRIGGERS) >= 5

    def test_mood_prompts_all_keys(self):
        from modules.puhlyash.persona import MOOD_PROMPTS
        for mood in ("sweet", "comfort", "light", "spicy", "quick", "classic", "summer", "special"):
            assert mood in MOOD_PROMPTS


class TestPuhlyashIntro:
    """get_puhlyash_intro() — генерация вступления."""

    def test_intro_returns_string(self):
        from modules.puhlyash.persona import get_puhlyash_intro
        intro = get_puhlyash_intro()
        assert isinstance(intro, str)
        assert len(intro) > 10

    def test_intro_with_mood(self):
        from modules.puhlyash.persona import get_puhlyash_intro
        intro = get_puhlyash_intro("sweet")
        assert isinstance(intro, str)
        assert len(intro) > 10

    def test_intro_all_moods(self):
        from modules.puhlyash.persona import get_puhlyash_intro, MOOD_PROMPTS
        for mood in MOOD_PROMPTS:
            intro = get_puhlyash_intro(mood)
            assert isinstance(intro, str)
            assert len(intro) > 10

    def test_intro_never_empty(self):
        from modules.puhlyash.persona import get_puhlyash_intro
        for _ in range(20):
            assert len(get_puhlyash_intro()) > 5


class TestFormatMessage:
    """format_puhlyash_message() — форматирование рецепта."""

    def test_format_with_minimal_recipe(self):
        from modules.puhlyash.persona import format_puhlyash_message
        recipe = {
            "title": "Тестовый рецепт",
            "description": "Описание",
            "ingredients": '["вода"]',
            "steps": '["вскипятить"]',
            "calories_per_serving": 100,
            "cook_time_minutes": 10,
            "servings": 1,
            "puhlyash_intro": "Привет!",
        }
        msg = format_puhlyash_message(recipe)
        assert "Пухляша" in msg or "Рецепт" in msg
        assert "Тестовый рецепт" in msg
        assert len(msg) > 20

    def test_format_with_empty_ingredients(self):
        from modules.puhlyash.persona import format_puhlyash_message
        recipe = {
            "title": "Пустой рецепт",
            "description": "",
            "ingredients": "[]",
            "steps": "[]",
            "calories_per_serving": 0,
            "cook_time_minutes": 0,
            "servings": 2,
            "puhlyash_intro": "Тест",
        }
        msg = format_puhlyash_message(recipe)
        assert "Пустой рецепт" in msg

    def test_format_with_irisochka_tip(self):
        from modules.puhlyash.persona import format_puhlyash_message
        recipe = {
            "title": "Тест",
            "description": "",
            "ingredients": '["мука"]',
            "steps": '["замесить"]',
            "calories_per_serving": 200,
            "cook_time_minutes": 30,
            "servings": 4,
            "puhlyash_intro": "Вступление",
        }
        msg = format_puhlyash_message(recipe, irisochka_tip="🐭 Ирисочка: Совет!")
        assert "Ирисочка" in msg


class TestIrisochka:
    """Ирисочка — быстрые советы."""

    def test_get_quick_tip_returns_string(self):
        from modules.puhlyash.irisochka import get_quick_tip
        tip = get_quick_tip()
        assert isinstance(tip, str)
        assert len(tip) > 5

    def test_quick_tip_contains_irisochka(self):
        from modules.puhlyash.irisochka import get_quick_tip
        tip = get_quick_tip()
        assert "Ирисочка" in tip or "🐭" in tip

    def test_quick_tip_all_unique(self):
        from modules.puhlyash.irisochka import _QUICK_FACTS
        assert len(set(_QUICK_FACTS)) == len(_QUICK_FACTS)

    def test_quick_tips_minimum_count(self):
        from modules.puhlyash.irisochka import _QUICK_FACTS
        assert len(_QUICK_FACTS) >= 3


class TestSysPrompts:
    """Системные промпты персонажей."""

    def test_puhlyash_sys_prompt_exists(self):
        from modules.puhlyash.persona import SYS_PUHLYASH
        assert "Пухляш" in SYS_PUHLYASH
        assert "рыжий кот" in SYS_PUHLYASH.lower()

    def test_irisochka_sys_prompt_exists(self):
        from modules.puhlyash.irisochka import SYS_IRISOCHKA
        assert "Ирисочка" in SYS_IRISOCHKA
        assert "нутрициолог" in SYS_IRISOCHKA.lower()

    def test_sys_prompt_has_json_structure(self):
        from modules.puhlyash.persona import SYS_PUHLYASH
        assert "title" in SYS_PUHLYASH
        assert "ingredients" in SYS_PUHLYASH
