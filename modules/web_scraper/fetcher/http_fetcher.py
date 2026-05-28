"""Web Scraper: requests + BS4. MVP без headless-браузера (нет OOM-риска)."""
import hashlib
import json
import re
import uuid
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from building_blocks.config import get_settings
from building_blocks.contracts import FetchFailReason
from building_blocks.logger import get_logger
from modules.web_scraper.network.ssrf_guard import validate_url_for_ssrf

log = get_logger(__name__)
cfg = get_settings()

MIN_TEXT_LENGTH = 100  # мин. символов для валидного контента


def _extract_text(html: str, url: str) -> str:
    """Boilerplate Remover: извлекаем основной текст."""
    soup = BeautifulSoup(html, "lxml")

    # Удаляем мусор
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "iframe", "noscript", "form", "button"]):
        tag.decompose()

    # Приоритет article/main
    for selector in ["article", "main", ".content", ".article", ".post", "#content"]:
        target = soup.select_one(selector)
        if target:
            text = target.get_text(separator=" ", strip=True)
            if len(text) >= MIN_TEXT_LENGTH:
                return _clean_text(text)

    # Fallback: body
    body = soup.find("body")
    if body:
        return _clean_text(body.get_text(separator=" ", strip=True))

    return _clean_text(soup.get_text(separator=" ", strip=True))


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    return text.strip()[:50000]  # Hard limit


async def fetch_url(url: str, task_id: str, trace_id: str) -> dict:
    """
    Returns dict with keys: ok, raw_text, content_sha256, http_status,
    fail_reason (if not ok).
    """
    # 1. SSRF Guard
    is_safe, reason = validate_url_for_ssrf(url)
    if not is_safe:
        log.warning("[%s] SSRF blocked: %s | %s", task_id, url, reason)
        return {"ok": False, "fail_reason": FetchFailReason.SECURITY_VIOLATION}

    # 2. HTTP request с таймаутом
    headers = {
        "User-Agent": cfg.scraper_user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    }
    try:
        async with httpx.AsyncClient(
            timeout=cfg.scraper_timeout_seconds,
            follow_redirects=True,
            max_redirects=3,
        ) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code >= 400:
            log.warning("[%s] HTTP %d for %s", task_id, resp.status_code, url)
            return {"ok": False, "fail_reason": FetchFailReason.HTTP_ERROR,
                    "http_status": resp.status_code}

        # 3. Извлекаем текст
        raw_text = _extract_text(resp.text, url)

        if len(raw_text) < MIN_TEXT_LENGTH:
            log.warning("[%s] Content too short (%d chars): %s", task_id, len(raw_text), url)
            return {"ok": False, "fail_reason": FetchFailReason.EMPTY_CONTENT}

        content_sha256 = hashlib.sha256(raw_text.encode()).hexdigest()
        log.info("[%s] Fetched %d chars from %s", task_id, len(raw_text), url)

        return {
            "ok": True,
            "raw_text": raw_text,
            "content_sha256": content_sha256,
            "http_status": resp.status_code,
            "content_length": len(raw_text),
        }

    except httpx.TimeoutException:
        log.warning("[%s] Timeout for %s", task_id, url)
        return {"ok": False, "fail_reason": FetchFailReason.TIMEOUT}
    except Exception as e:
        log.error("[%s] Fetch error for %s: %s", task_id, url, e)
        return {"ok": False, "fail_reason": FetchFailReason.HTTP_ERROR}