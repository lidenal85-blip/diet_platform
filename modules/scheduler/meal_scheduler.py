"""APScheduler — планировщик питания и уведомлений."""
import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import aiosqlite
from database import DB_PATH
from modules.notifier.sender import send_notification
from modules.recipes.engine import generate_recipe
from modules.fitness.engine import generate_exercises, format_exercises

log = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

MEAL_EMOJI = {"breakfast": "🌅", "lunch": "🍽", "dinner": "🌙"}
MEAL_LABEL = {"breakfast": "Завтрак", "lunch": "Обед", "dinner": "Ужин"}


async def _get_active_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT tg_id, meal_breakfast, meal_lunch, meal_dinner, "
            "active_diet_mode, notifications_enabled FROM user_profiles "
            "WHERE notifications_enabled=1"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def send_meal_notification(meal: str):
    """Called by scheduler for breakfast/lunch/dinner."""
    users = await _get_active_users()
    log.info("Sending %s notifications to %d users", meal, len(users))

    for user in users:
        if not user.get("notify_personal", 1) or not user.get("notify_meals", 1):
            continue
        meal_time = user.get(f"meal_{meal}")
        if not meal_time:
            continue
        tg_id = user["tg_id"]
        diet_mode = user.get("active_diet_mode") or "home"
        try:
            from modules.puhlyash.persona import generate_puhlyash_recipe, format_puhlyash_message
            recipe, exercises = await asyncio.gather(
                generate_puhlyash_recipe(profile=dict(user)),
                generate_exercises(meal, diet_mode),
            )
            emoji = MEAL_EMOJI[meal]
            text = (
                f"{emoji} <b>{MEAL_LABEL[meal]}!</b>\n\n"
                f"{format_puhlyash_message(recipe)}\n\n"
                f"{format_exercises(exercises)}"
            )
            await send_notification(tg_id, text)
            await asyncio.sleep(0.5)
        except Exception as e:
            log.error("Failed notification for %s: %s", tg_id, e)


def _parse_time(t: str) -> tuple[int, int]:
    """'08:30' -> (8, 30)"""
    h, m = t.split(":")
    return int(h), int(m)


async def reschedule_user(tg_id: str, breakfast: str, lunch: str, dinner: str):
    """Add/update cron jobs for a specific user."""
    for meal, time_str in [("breakfast", breakfast), ("lunch", lunch), ("dinner", dinner)]:
        job_id = f"{meal}_{tg_id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        if time_str:
            h, m = _parse_time(time_str)
            scheduler.add_job(
                send_meal_notification,
                CronTrigger(hour=h, minute=m),
                args=[meal],
                id=job_id,
                replace_existing=True,
            )
            log.info("Scheduled %s for user %s at %s", meal, tg_id, time_str)


async def load_all_schedules():
    """Load all user schedules on startup."""
    users = await _get_active_users()
    for u in users:
        b = u.get("meal_breakfast") or ""
        l = u.get("meal_lunch") or ""
        d = u.get("meal_dinner") or ""
        if any([b, l, d]):
            await reschedule_user(u["tg_id"], b, l, d)
    log.info("Loaded schedules for %d users", len(users))


def start_scheduler():
    scheduler.start()
    log.info("⏰ Scheduler started")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()