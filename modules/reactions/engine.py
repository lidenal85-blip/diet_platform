"""Reactions: лайк/дизлайк/сохранить для рецептов/диет/упражнений."""
import uuid
import aiosqlite
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import DB_PATH


def reaction_kb(item_type: str, item_id: str) -> InlineKeyboardMarkup:
    """Инлайн-клавиатура реакций."""
    prefix = f"{item_type}:{item_id}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👍", callback_data=f"react:like:{prefix}"),
            InlineKeyboardButton(text="👎", callback_data=f"react:dislike:{prefix}"),
            InlineKeyboardButton(text="🔖 Сохранить", callback_data=f"react:save:{prefix}"),
        ],
        [
            InlineKeyboardButton(text="🔄 Альтернативы", callback_data=f"react:alt:{prefix}"),
            InlineKeyboardButton(text="💡 Развить", callback_data=f"react:expand:{prefix}"),
        ],
    ])


def reaction_kb_with_reason(item_type: str, item_id: str, reaction: str) -> InlineKeyboardMarkup:
    """После лайка/дизлайка — предложить указать причину."""
    prefix = f"{item_type}:{item_id}"
    if reaction == "dislike":
        reasons = [
            ("🕒 Долго готовить", "too_long"),
            ("💸 Дорогие продукты", "too_expensive"),
            ("🧐 Не мои ингредиенты", "bad_ingredients"),
            ("😕 Не мой вкус", "not_my_taste"),
            ("👎 Просто не нравится", "just_no"),
        ]
    else:
        reasons = [
            ("🔥 Очень вкусно", "delicious"),
            ("⚡ Быстро готовится", "quick"),
            ("💰 Дешёво", "cheap"),
            ("🥗 Полезно", "healthy"),
        ]
    rows = [[InlineKeyboardButton(text=t, callback_data=f"reason:{r}:{prefix}")] for t, r in reasons]
    rows.append([InlineKeyboardButton(text="✔️ Без причины", callback_data=f"reason:skip:{prefix}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def save_reaction(tg_id: str, item_type: str, item_id: str,
                        item_title: str, reaction: str, reason: str = None):
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        # Удаляем предыдущую реакцию на этот item
        await db.execute(
            "DELETE FROM reactions WHERE tg_id=? AND item_type=? AND item_id=?",
            (tg_id, item_type, item_id)
        )
        await db.execute(
            "INSERT INTO reactions (id, tg_id, item_type, item_id, item_title, reaction, reason) "
            "VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), tg_id, item_type, item_id, item_title, reaction, reason)
        )
        await db.commit()


async def get_saved(tg_id: str, item_type: str = None) -> list:
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        if item_type:
            async with db.execute(
                "SELECT * FROM reactions WHERE tg_id=? AND item_type=? AND reaction='save' ORDER BY created_at DESC",
                (tg_id, item_type)
            ) as c:
                return [dict(r) for r in await c.fetchall()]
        else:
            async with db.execute(
                "SELECT * FROM reactions WHERE tg_id=? AND reaction='save' ORDER BY created_at DESC",
                (tg_id,)
            ) as c:
                return [dict(r) for r in await c.fetchall()]