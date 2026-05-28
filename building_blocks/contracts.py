"""Shared Kernel: неизменяемые контракты обмена между модулями."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid


class PipelineStatus(str, Enum):
    CREATED = "created"
    SEARCHING = "searching"
    SCRAPING = "scraping"
    EXTRACTING = "extracting"
    REGISTERING = "registering"
    COMPLETED = "completed"
    FAILED = "failed"
    POSTPONED = "postponed"


class DietStatus(str, Enum):
    DRAFT = "draft"
    PENDING_VERIFICATION = "pending_verification"
    APPROVED = "approved"
    FLAGGED = "flagged"
    ARCHIVED = "archived"


class FetchFailReason(str, Enum):
    SECURITY_VIOLATION = "security_violation"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    PARSE_ERROR = "parse_error"
    EMPTY_CONTENT = "empty_content"
    MAX_RETRIES_EXCEEDED = "max_retries_exceeded"


@dataclass(frozen=True)
class SearchUrlsDiscoveredEvent:
    session_id: str
    trace_id: str
    query_text: str
    urls: list
    discovered_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class ContentFetchedEvent:
    task_id: str
    session_id: str
    trace_id: str
    source_url: str
    raw_cleaned_text: str
    content_sha256: str
    scraped_at: datetime = field(default_factory=datetime.utcnow)
    http_status: int = 200
    content_length: int = 0


@dataclass(frozen=True)
class ContentFetchFailedEvent:
    task_id: str
    session_id: str
    trace_id: str
    source_url: str
    reason: FetchFailReason
    attempt: int
    failed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class SubmitDietDraftCommand:
    draft_id: str
    session_id: str
    trace_id: str
    source_url: str
    content_sha256: str
    diet_name: str
    allowed_foods: list
    forbidden_foods: list
    menu_structure: dict
    contraindications: list
    conditions: list
    confidence_score: float
    raw_text_excerpt: str
    extracted_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class DietMasterPublishedEvent:
    diet_id: str
    session_id: str
    trace_id: str
    diet_name: str
    status: DietStatus
    version: int
    published_at: datetime = field(default_factory=datetime.utcnow)


def new_trace_id() -> str:
    return str(uuid.uuid4())


def new_session_id() -> str:
    return str(uuid.uuid4())