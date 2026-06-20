"""Userbot — отправка уведомлений через Userbot Relay (den4ik-claude).

CONFLICT-01 fix: раньше diet_platform держал собственный Pyrogram Client на
той же сессии (/opt/telegram-agent-book/my_account.session), что конфликтовало с
den4ik-claude (тоже владелец этого проекта) и давало 100% ошибок `database is locked`.

Теперь den4ik-claude — единственный владелец сессии и держит локальный
HTTP-relay на 127.0.0.1:8190 (см. /opt/den4ik-claude/userbot_relay.py). diet_platform
просто дёргает этот endpoint через httpx — без собственного Pyrogram-клиента.
"""
import logging
import httpx

from building_blocks.config import get_settings

log = logging.getLogger(__name__)
cfg = get_settings()

RELAY_URL = "http://127.0.0.1:8190/relay/send"
RELAY_TOKEN = cfg.userbot_relay_token
RELAY_TIMEOUT = 10.0


async def send_notification(tg_id: int | str, text: str) -> bool:
    """Отправляет уведомление через Userbot Relay. Сигнатура совместима
    со старым send_notification() — вызывающий код (scheduler/meal_scheduler.py и т.д.)
    не меняется.
    """
    if not RELAY_TOKEN:
        log.error("USERBOT_RELAY_TOKEN не задан в .env, отправка невозможна")
        return False

    try:
        async with httpx.AsyncClient(timeout=RELAY_TIMEOUT) as client:
            resp = await client.post(
                RELAY_URL,
                json={"chat_id": int(tg_id), "text": text[:4096], "parse_mode": "html"},
                headers={"X-Relay-Token": RELAY_TOKEN},
            )
        if resp.status_code == 200:
            return True
        log.warning("Relay send failed for %s: HTTP %d %s",
                    tg_id, resp.status_code, resp.text[:200])
        return False
    except httpx.ConnectError:
        log.error("Userbot Relay недоступен (den4ik-claude не запущен?): %s", RELAY_URL)
        return False
    except Exception as e:
        log.error("Relay send error for %s: %s", tg_id, e)
        return False


async def stop_client() -> None:
    """No-op: diet_platform больше не владеет Pyrogram-клиентом.
    Сохранена для совместимости с вызывающим кодом (shutdown hooks).
    """
    return None