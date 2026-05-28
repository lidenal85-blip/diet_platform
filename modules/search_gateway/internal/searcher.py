"""Search Gateway: DuckDuckGo HTML scraping + SERP fallback.

Responsibility:
- Оркестрация поисковых провайдеров
- Rate limiting + fallback strategy
- Генерация Correlation ID
- Запись задач в Outbox (Транзакционный Outbox)
"""
import json
import hashlib
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Optional
import httpx
from bs4 import BeautifulSoup
import aiosqlite

from building_blocks.config import get_settings
from building_blocks.logger import get_logger, set_trace_context
from building_blocks.contracts import PipelineStatus, new_trace_id

log = get_logger(__name__)
cfg = get_settings()

DDG_URL = "https://html.duckduckgo.com/html/"
DDG_HEADERS = {
    "User-Agent": cfg.scraper_user_agent,
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


def _query_cache_key(query: str) -> str:
    return hashlib.sha256(query.lower().strip().encode()).hexdigest()


async def _check_cache(db: aiosqlite.Connection, cache_key: str) -> Optional[list]:
    """TTL-кэш поисковой выдачи."""
    ttl_cutoff = (datetime.utcnow() - timedelta(hours=cfg.search_cache_ttl_hours)).isoformat()
    async with db.execute(
        "SELECT payload FROM outbox WHERE event_type='search_cache' "
        "AND json_extract(payload,'$.cache_key')=? AND created_at>? LIMIT 1",
        (cache_key, ttl_cutoff)
    ) as cur:
        row = await cur.fetchone()
        if row:
            data = json.loads(row[0])
            return data.get("urls", [])
    return None


async def _scrape_duckduckgo(query: str) -> list:
    """Fallback: HTML-скрапинг DuckDuckGo."""
    diet_query = f"{query} диета план питания медицинский"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.post(
                DDG_URL,
                data={"q": diet_query, "kl": "ru-ru"},
                headers=DDG_HEADERS,
            )
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        urls = []
        for a in soup.select(".result__url"):
            href = a.get("href", "").strip()
            if href.startswith("http") and len(urls) < cfg.max_urls_per_query:
                urls.append(href)
        log.info("DuckDuckGo found %d URLs for query: %s", len(urls), query[:50])
        return urls
    except Exception as e:
        log.warning("DuckDuckGo scraping failed: %s", e)
        return []


async def initiate_search(
    db: aiosqlite.Connection,
    query_text: str,
    user_id: Optional[str] = None,
) -> str:
    """
    Entry point: создаёт SearchSession, запускает поиск, пишет в Outbox.
    Returns: session_id
    """
    session_id = str(uuid.uuid4())
    trace_id = new_trace_id()
    set_trace_context(trace_id, session_id)

    # 1. Создаём сессию
    await db.execute(
        "INSERT INTO search_sessions(id, trace_id, query_text, status, user_id) "
        "VALUES(?,?,?,?,?)",
        (session_id, trace_id, query_text, PipelineStatus.SEARCHING, user_id)
    )

    # 2. Проверяем кэш
    cache_key = _query_cache_key(query_text)
    cached_urls = await _check_cache(db, cache_key)

    if cached_urls:
        log.info("Cache hit for query: %s", query_text[:50])
        urls = cached_urls
    else:
        # 3. Делаем поиск
        urls = await _scrape_duckduckgo(query_text)
        if not urls:
            await db.execute(
                "UPDATE search_sessions SET status=?, error_message=?, updated_at=datetime('now') WHERE id=?",
                (PipelineStatus.FAILED, "No URLs found", session_id)
            )
            await db.commit()
            log.warning("Search failed: no URLs for query: %s", query_text[:50])
            return session_id

    # 4. Транзакционно пишем Outbox-задачи для каждого URL
    for url in urls:
        task_id = str(uuid.uuid4())
        payload = json.dumps({
            "task_id": task_id,
            "session_id": session_id,
            "trace_id": trace_id,
            "url": url,
            "query_text": query_text,
        })
        await db.execute(
            "INSERT INTO outbox(id, session_id, trace_id, event_type, payload, status) "
            "VALUES(?,?,?,?,?,?)",
            (task_id, session_id, trace_id, "fetch_url", payload, "pending")
        )

    # 5. Атомарно коммитим
    await db.commit()
    log.info("Session %s created with %d URLs", session_id, len(urls))
    return session_id