"""Отправка уведомлений через собственный aiogram-бот diet_platform.

CONFLICT-01 history: раньше diet_platform держал собственный Pyrogram Client на общей
session с den4ik-claude — давало database is locked. Потом перешли на Userbot Relay
(httpx -> Pyrogram внутри den4ik-claude).

2026-06-30: den4ik-claude мигрировал на leviathan_hub_bot.py, который вообще не
использует Pyrogram — решение владельца: userbot больше не нужен вообще.
Уведомления теперь идут через обычный aiogram Bot API собственным токеном diet_platform
(TELEGRAM_BOT_TOKEN из .env) — никакой зависимости от den4ik-claude/Pyrogram больше нет.
Короткоживущий Bot()-инстанс на каждую отправку — стандартная практика aiogram для
одиночных отправок из фоновых задач (scheduler), не связанных с long-polling в bot.py.
"""
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from building_blocks.config import get_settings

log = logging.getLogger(__name__)
cfg = get_settings()


async def send_notification(tg_id: int | str, text: str) -> bool:
    """Отправляет уведомление через собственный Bot API diet_platform.
    Сигнатура совместима со старым send_notification() — вызывающий код
    (scheduler/meal_scheduler.py и т.д.) не меняется.
    """
    if not cfg.telegram_bot_token:
        log.error("TELEGRAM_BOT_TOKEN не задан в .env, отправка невозможна")
        return False

    bot = Bot(
        token=cfg.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await bot.send_message(int(tg_id), text[:4096])
        return True
    except TelegramAPIError as e:
        log.warning("Notification send failed for %s: %s", tg_id, e)
        return False
    except Exception as e:
        log.error("Notification send error for %s: %s", tg_id, e)
        return False
    finally:
        await bot.session.close()


async def stop_client() -> None:
    """No-op: каждая отправка сама закрывает свою сессию (см. finally выше).
    Сохранена для совместимости с вызывающим кодом (shutdown hooks).
    """
    return None