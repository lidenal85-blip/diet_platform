"""Единый источник клавиатур Telegram-бота «Пухляш» (C-3.1, 2026-09-19).

Решение C-3.1 (аудит `C3_AUDIT_2026-09-19.md` §7-2, §12-2, одобрено владельцем):
главная Reply-клавиатура раньше определялась в двух местах с РАЗНЫМ набором
кнопок — источник расползания меню. Теперь оба варианта живут здесь, канонический
импорт — только из этого модуля:

- ``MAIN_KEYBOARD_CANONICAL`` — вариант ``bot.py`` (9 кнопок, без «🐈 Пухляш»):
  используется стартовым/системным слоем (bot.py) → ``canonical_main_kb()``;
- ``MAIN_KEYBOARD_LEGACY`` — вариант ``bot_handlers.recipes.main_kb``
  (10 кнопок, последняя строка «🐈 Пухляш»): используется хендлерами →
  ``legacy_main_kb()`` / диспетчер-обёртка ``main_kb()``.

ВАЖНО (ограничения этапа C-3.1): тексты кнопок, порядок, размеры и условия
отображения сохранены БЕЗ ИЗМЕНЕНИЙ — объединение двух вариантов сознательно
не делается, т.к. это изменило бы видимое пользователю поведение (флаг
``show_puhlyash_button`` остаётся решением этапа C-3.5 «меню»).

Консолидация диспетчер-обёрток: 5 модулей-хендлеров ранее держали свои
``_main_kb()``/``main_kb()``, делегирующие в ``recipes.main_kb``. Теперь все
они импортируют обёртку отсюда; делегаты в модулях сохранены (compat- shim,
перенаправляют сюда) — поведение и имена без изменений.

C-3.2 (2026-09-19): в ОБА варианта добавлена кнопка «📅 Сегодня» — вход в
экран дня (``bot_handlers.today``). Существующие кнопки не тронуты.

C-3.3 (2026-09-21): в ОБА варианта добавлена кнопка «🗓 Мой план» — вход в
экран недели (``bot_handlers.my_plan``). Существующие кнопки не тронуты.
"""
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

__all__ = [
    "MAIN_KEYBOARD_CANONICAL",
    "MAIN_KEYBOARD_LEGACY",
    "canonical_main_kb",
    "legacy_main_kb",
    "main_kb",
]

# ── Канонический вариант (бывший bot.py MAIN_KEYBOARD, 9 кнопок) ──
# C-3.2: добавлена кнопка «📅 Сегодня» (вход в экран дня, handler bot_handlers.today)
# в последнюю строку; существующие кнопки, их тексты и порядок не менялись.
MAIN_KEYBOARD_CANONICAL = ReplyKeyboardMarkup(  # 9 кнопок + «🗓 Мой план» (C-3.3)
    keyboard=[
        [KeyboardButton(text="🎯 Подобрать диету"), KeyboardButton(text="👤 Кабинет")],
        [KeyboardButton(text="🍝 Рецепт от Пухляша"), KeyboardButton(text="👨‍🍳 Рецепты")],
        [KeyboardButton(text="🧊 Холодильник"), KeyboardButton(text="💰 По бюджету")],
        [KeyboardButton(text="👨‍🍳 Шеф на телефоне"), KeyboardButton(text="⏰ Расписание")],
        [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="ℹ️ Помощь")],
        [KeyboardButton(text="🗓 Мой план")],
    ],
    resize_keyboard=True,
    persistent=True,
)

# ── Легаси-вариант хендлеров (бывший recipes.main_kb, 10 кнопок) ──
# C-3.2: «📅 Сегодня» добавлена НОВОЙ строкой (сетка 2 колонки заполнена);
# все существующие кнопки, их порядок и расположение не менялись.
MAIN_KEYBOARD_LEGACY = ReplyKeyboardMarkup(  # 10 кнопок + «🗓 Мой план» (C-3.3)
    keyboard=[
        [KeyboardButton(text="🎯 Подобрать диету"), KeyboardButton(text="👤 Кабинет")],
        [KeyboardButton(text="🍝 Рецепт от Пухляша"), KeyboardButton(text="👨‍🍳 Рецепты")],
        [KeyboardButton(text="🧊 Холодильник"), KeyboardButton(text="💰 По бюджету")],
        [KeyboardButton(text="👨‍🍳 Шеф на телефоне"), KeyboardButton(text="⏰ Расписание")],
        [KeyboardButton(text="🐈 Пухляш"), KeyboardButton(text="ℹ️ Помощь")],
        [KeyboardButton(text="📅 Сегодня")],
        [KeyboardButton(text="🗓 Мой план")],
    ],
    resize_keyboard=True,
    persistent=True,
)


def canonical_main_kb() -> ReplyKeyboardMarkup:
    """Главная клавиатура bot.py (9 кнопок, без «🐈 Пухляш»)."""
    return MAIN_KEYBOARD_CANONICAL


def legacy_main_kb() -> ReplyKeyboardMarkup:
    """Главная клавиатура хендлеров (10 кнопок, с «🐈 Пухляш»)."""
    return MAIN_KEYBOARD_LEGACY


def main_kb() -> ReplyKeyboardMarkup:
    """Диспетчер-обёртка: совместимое имя для хендлеров (бывш. recipes.main_kb)."""
    return legacy_main_kb()
