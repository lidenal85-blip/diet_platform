"""Pipeline Worker: читает Outbox -> парсит -> экстрагирует -> регистрирует.

Transactional Outbox pattern: все задачи в SQLite, нет потери при рестарте.
"""
import asyncio
import json
import uuid
from datetime import datetime, timedelta
import aiosqlite

from building_blocks.config import get_settings
from building_blocks.contracts import PipelineStatus, FetchFailReason
from building_blocks.logger import get_logger, set_trace_context
from database import DB_PATH
from modules.web_scraper.fetcher.http_fetcher import fetch_url
from modules.diet_extractor.engine.gemini_extractor import extract_diet
from modules.diet_registry.infrastructure.repository import register_diet_draft

log = get_logger(__name__)
cfg = get_settings()

_semaphore: asyncio.Semaphore = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(cfg.worker_max_concurrent)
    return _semaphore


async def _process_fetch_task(db: aiosqlite.Connection, task: dict) -> None:
    """Fetch URL -> Extract -> Register в одном pipeline."""
    payload = json.loads(task["payload"])
    task_id = task["id"]
    session_id = payload["session_id"]
    trace_id = payload["trace_id"]
    url = payload["url"]

    set_trace_context(trace_id, session_id)
    log.info("➔ Processing task %s | url=%s", task_id, url)

    # Mark as processing
    await db.execute(
        "UPDATE outbox SET status='processing', attempt=attempt+1 WHERE id=?",
        (task_id,)
    )
    await db.commit()

    try:
        # Step 1: Fetch
        result = await fetch_url(url, task_id, trace_id)

        if not result["ok"]:
            fail_reason = result["fail_reason"]
            log.warning("[❌] Fetch failed: %s | %s", task_id, fail_reason)
            await _handle_failure(db, task, str(fail_reason), payload)
            return

        # Save snapshot
        await db.execute(
            """INSERT OR IGNORE INTO web_snapshots
               (id, session_id, trace_id, source_url, content_sha256,
                raw_text_length, http_status)
               VALUES(?,?,?,?,?,?,?)""",
            (task_id, session_id, trace_id, url,
             result["content_sha256"], result["content_length"],
             result["http_status"])
        )

        # Step 2: Extract
        draft_cmd = await extract_diet(
            raw_text=result["raw_text"],
            source_url=url,
            session_id=session_id,
            trace_id=trace_id,
            content_sha256=result["content_sha256"],
        )

        if draft_cmd is None:
            log.info("[⏭] Low confidence, sending to DLQ: %s", task_id)
            await _to_dlq(db, task, "LOW_CONFIDENCE", payload)
            await db.execute(
                "UPDATE outbox SET status='dlq' WHERE id=?", (task_id,)
            )
            await _update_session_progress(db, session_id)  # BUG-03 fix
            await db.commit()
            return

        # Step 3: Register (sync call)
        diet_id, status = await register_diet_draft(db, draft_cmd)
        log.info("[✅] Registered diet=%s status=%s", diet_id, status.value)

        # Mark outbox done
        await db.execute(
            "UPDATE outbox SET status='done', processed_at=datetime('now') WHERE id=?",
            (task_id,)
        )

        # Update session status
        await _update_session_progress(db, session_id)
        await db.commit()

    except Exception as e:
        log.error("[❌] Unexpected error in task %s: %s", task_id, e, exc_info=True)
        await _handle_failure(db, task, str(e), payload)


async def _handle_failure(
    db: aiosqlite.Connection, task: dict, error: str, payload: dict
) -> None:
    attempt = task["attempt"] + 1
    max_attempts = task["max_attempts"]

    session_id = payload.get("session_id", "-")
    if attempt >= max_attempts:
        log.warning("Max attempts reached for task %s, moving to DLQ", task["id"])
        await _to_dlq(db, task, error, payload)
        await db.execute(
            "UPDATE outbox SET status='dlq', error=? WHERE id=?",
            (error, task["id"])
        )
        await _update_session_progress(db, session_id)  # BUG-03 fix
    else:
        # Exponential backoff: 2^attempt * 5 seconds
        delay_seconds = min(5 * (2 ** attempt), 300)
        scheduled = (datetime.utcnow() + timedelta(seconds=delay_seconds)).isoformat()
        await db.execute(
            "UPDATE outbox SET status='pending', attempt=?, error=?, scheduled_at=? WHERE id=?",
            (attempt, error, scheduled, task["id"])
        )
        log.info("Task %s rescheduled in %ds (attempt %d/%d)",
                 task["id"], delay_seconds, attempt, max_attempts)
    await db.commit()


async def _to_dlq(
    db: aiosqlite.Connection, task: dict, reason: str, payload: dict
) -> None:
    await db.execute(
        """INSERT OR IGNORE INTO dlq
           (id, outbox_id, session_id, trace_id, event_type, payload, reason)
           VALUES(?,?,?,?,?,?,?)""",
        (
            str(uuid.uuid4()), task["id"],
            task["session_id"], task["trace_id"],
            task["event_type"], task["payload"], reason
        )
    )


async def _update_session_progress(db: aiosqlite.Connection, session_id: str) -> None:
    async with db.execute(
        "SELECT COUNT(*) as total FROM outbox WHERE session_id=?", (session_id,)
    ) as cur:
        total_row = await cur.fetchone()
    async with db.execute(
        "SELECT COUNT(*) as done FROM outbox WHERE session_id=? AND status IN ('done','dlq')",
        (session_id,)
    ) as cur:
        done_row = await cur.fetchone()

    total = total_row[0] if total_row else 1
    done = done_row[0] if done_row else 0

    if done >= total:
        await db.execute(
            "UPDATE search_sessions SET status=?, updated_at=datetime('now') WHERE id=?",
            (PipelineStatus.COMPLETED.value, session_id)
        )


async def run_worker_loop() -> None:
    """Main worker loop: поллинг Outbox каждые N секунд."""
    log.info("▶ Pipeline worker started (poll=%ds, concurrent=%d)",
             cfg.worker_poll_interval_seconds, cfg.worker_max_concurrent)
    sem = _get_semaphore()

    while True:
        try:
            async with aiosqlite.connect(DB_PATH, timeout=30) as db:
                db.row_factory = aiosqlite.Row
                now = datetime.utcnow().isoformat()

                async with db.execute(
                    """SELECT * FROM outbox
                       WHERE status='pending' AND scheduled_at<=?
                       ORDER BY created_at ASC LIMIT ?""",
                    (now, cfg.worker_max_concurrent)
                ) as cur:
                    tasks = await cur.fetchall()

                if tasks:
                    log.info("📦 Found %d pending tasks", len(tasks))
                    coros = [
                        _run_with_semaphore(sem, db, dict(t))
                        for t in tasks
                    ]
                    await asyncio.gather(*coros, return_exceptions=True)

        except Exception as e:
            log.error("❌ Worker loop error: %s", e, exc_info=True)

        await asyncio.sleep(cfg.worker_poll_interval_seconds)


async def _run_with_semaphore(
    sem: asyncio.Semaphore,
    db: aiosqlite.Connection,
    task: dict,
) -> None:
    async with sem:
        await _process_fetch_task(db, task)