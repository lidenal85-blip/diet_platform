"""Delivery API: FastAPI REST endpoints.

Read-only. CQRS. Singleflight для защиты от Cache Stampede.
"""
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import aiosqlite
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from building_blocks.config import get_settings
from building_blocks.contracts import new_trace_id, new_session_id, PipelineStatus
from building_blocks.logger import get_logger, set_trace_context
from database import init_db, DB_PATH
from modules.search_gateway.internal.searcher import initiate_search
from modules.diet_registry.infrastructure.repository import (
    get_diet_by_id, search_diets, verify_diet
)
from workers.pipeline_worker import run_worker_loop

log = get_logger(__name__)
cfg = get_settings()

# Singleflight: ключ -> Future
_singleflight: dict[str, asyncio.Future] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    log.info("✅ Diet Platform started on port %d", cfg.app_port)
    worker_task = asyncio.create_task(run_worker_loop())
    yield
    worker_task.cancel()
    log.info("⏹ Diet Platform stopped")


app = FastAPI(
    title="Diet Platform API",
    version="1.0.0",
    description="Автоматизированный сбор и выдача медицинских планов питания",
    lifespan=lifespan,
)


class SearchRequest(BaseModel):
    query: str
    user_id: Optional[str] = None


class VerifyRequest(BaseModel):
    approved: bool
    actor: str = "moderator"


@app.get("/health")
async def health():
    return {"status": "ok", "service": "diet-platform", "version": "1.0.0"}


@app.post("/api/v1/search", status_code=202)
async def start_search(req: SearchRequest):
    """
    Async: возвращает session_id немедленно.
    Клиент опрашивает /api/v1/sessions/{id} для статуса.
    """
    if not req.query or len(req.query.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query too short")
    if len(req.query) > 500:
        raise HTTPException(status_code=400, detail="Query too long")

    trace_id = new_trace_id()
    set_trace_context(trace_id)

    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        session_id = await initiate_search(db, req.query.strip(), req.user_id)

    return {
        "session_id": session_id,
        "trace_id": trace_id,
        "status": "accepted",
        "message": "Запрос принят. Опрашивайте /api/v1/sessions/{session_id} для статуса.",
    }


@app.get("/api/v1/sessions/{session_id}")
async def get_session_status(session_id: str):
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM search_sessions WHERE id=?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")

        async with db.execute(
            "SELECT status, COUNT(*) as cnt FROM outbox WHERE session_id=? GROUP BY status",
            (session_id,)
        ) as cur:
            stats = {r["status"]: r["cnt"] for r in await cur.fetchall()}

    return {
        "session_id": session_id,
        "status": row["status"],
        "query": row["query_text"],
        "created_at": row["created_at"],
        "tasks": stats,
    }


@app.get("/api/v1/diets")
async def list_diets(
    q: Optional[str] = Query(None, max_length=200),
    status: str = Query("approved"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    # Singleflight для защиты от Cache Stampede
    cache_key = f"diets:{q}:{status}:{limit}:{offset}"
    if cache_key in _singleflight:
        return await _singleflight[cache_key]

    fut = asyncio.get_event_loop().create_future()
    _singleflight[cache_key] = fut

    try:
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            db.row_factory = aiosqlite.Row
            diets = await search_diets(db, query=q or "", status=status,
                                       limit=limit, offset=offset)
        result = {"items": diets, "count": len(diets)}
        fut.set_result(result)
        return result
    except Exception as e:
        fut.set_exception(e)
        raise
    finally:
        _singleflight.pop(cache_key, None)


@app.get("/api/v1/diets/{diet_id}")
async def get_diet(diet_id: str):
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        diet = await get_diet_by_id(db, diet_id)
    if not diet:
        raise HTTPException(status_code=404, detail="Diet not found")
    return diet


@app.post("/api/v1/diets/{diet_id}/verify")
async def verify_diet_endpoint(diet_id: str, req: VerifyRequest):
    """Moderator endpoint: одобрение/отклонение диеты."""
    trace_id = new_trace_id()
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        ok = await verify_diet(db, diet_id, req.approved, req.actor, trace_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Version conflict or diet not found")
    return {"ok": True, "diet_id": diet_id, "approved": req.approved}


@app.get("/api/v1/pending")
async def list_pending(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Moderation queue: диеты на проверке."""
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        diets = await search_diets(db, status="pending_verification",
                                   limit=limit, offset=offset)
    return {"items": diets, "count": len(diets)}


@app.get("/api/v1/dlq")
async def list_dlq(limit: int = Query(20, ge=1, le=100)):
    """DLQ: необработанные задачи для инженеров."""
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM dlq ORDER BY failed_at DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
    return {"items": [dict(r) for r in rows], "count": len(rows)}




@app.post("/api/v1/dlq/retry-all")
async def retry_dlq_all():
    """DLQ Retry Dashboard: возвращает все DLQ-задачи в pending."""
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM dlq") as cur:
            items = await cur.fetchall()
        count = 0
        for item in items:
            d = dict(item)
            # Возвращаем в outbox с обнулённым attempt
            await db.execute(
                "UPDATE outbox SET status='pending', attempt=0, error=NULL, "
                "scheduled_at=datetime('now') WHERE id=?",
                (d["outbox_id"],)
            )
            count += 1
        await db.commit()
    return {"retried": count}


@app.delete("/api/v1/dlq/{dlq_id}")
async def delete_dlq_item(dlq_id: str):
    """DLQ: удалить запись вручную."""
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute("DELETE FROM dlq WHERE id=?", (dlq_id,))
        await db.commit()
    return {"ok": True, "deleted": dlq_id}
# Cabinet web UI
from api.cabinet_router import router as cabinet_router  # noqa
app.include_router(cabinet_router)

# Mini App
from api.miniapp_router import router as miniapp_router  # noqa
app.include_router(miniapp_router)