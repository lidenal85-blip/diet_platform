"""App bootstrap: FastAPI + Telegram Bot + Worker в одном процессе."""
import asyncio
import sys
import os

sys.path.insert(0, "/opt/diet_platform")

from building_blocks.config import get_settings
from building_blocks.logger import get_logger

log = get_logger("bootstrap")
cfg = get_settings()


async def main():
    import uvicorn
    from modules.delivery_api.controllers.api import app

    tasks = []

    # FastAPI
    config = uvicorn.Config(
        app,
        host=cfg.app_host,
        port=cfg.app_port,
        log_level="info",
        access_log=True,
    )
    server = uvicorn.Server(config)
    tasks.append(asyncio.create_task(server.serve()))

    # Telegram Bot (optional)
    if cfg.telegram_bot_token:
        from bot import start_bot
        tasks.append(asyncio.create_task(start_bot()))
        log.info("🤖 Telegram bot enabled")
    else:
        log.warning("⚠️ TELEGRAM_BOT_TOKEN not set, bot disabled")

    log.info("🚀 Diet Platform starting on %s:%d", cfg.app_host, cfg.app_port)
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())