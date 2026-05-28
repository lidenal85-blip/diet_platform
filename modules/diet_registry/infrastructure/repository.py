"""Diet Core Registry: хранение, валидация, OCC-версионирование, Audit Log."""
import json
import uuid
from datetime import datetime
from typing import Optional
import aiosqlite

from building_blocks.config import get_settings
from building_blocks.contracts import SubmitDietDraftCommand, DietStatus
from building_blocks.logger import get_logger
from modules.diet_registry.domain.medical_guard import validate_diet_draft

log = get_logger(__name__)
cfg = get_settings()


async def register_diet_draft(
    db: aiosqlite.Connection,
    cmd: SubmitDietDraftCommand,
) -> tuple[str, DietStatus]:
    """
    Idempotent: проверяет content_sha256 перед вставкой.
    Returns (diet_id, status).
    """
    # Idempotency: если уже есть — не дублируем
    async with db.execute(
        "SELECT id, status FROM diet_master WHERE content_sha256=?",
        (cmd.content_sha256,)
    ) as cur:
        existing = await cur.fetchone()
    if existing:
        log.info("[%s] Duplicate diet (sha256=%s), skipping", cmd.trace_id, cmd.content_sha256[:8])
        return existing["id"], DietStatus(existing["status"])

    # Medical Guard validation
    draft_data = {
        "diet_name": cmd.diet_name,
        "allowed_foods": cmd.allowed_foods,
        "forbidden_foods": cmd.forbidden_foods,
        "conditions": cmd.conditions,
        "contraindications": cmd.contraindications,
    }
    is_valid, issues = validate_diet_draft(draft_data)

    diet_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    if not is_valid:
        log.warning("[%s] Diet flagged: %s", cmd.trace_id, issues)
        status = DietStatus.FLAGGED
    elif cmd.confidence_score >= cfg.auto_publish_threshold:
        status = DietStatus.PENDING_VERIFICATION
    else:
        status = DietStatus.PENDING_VERIFICATION

    # Сохраняем DietMaster
    await db.execute(
        """INSERT INTO diet_master(
            id, session_id, trace_id, source_url, content_sha256,
            diet_name, allowed_foods, forbidden_foods, menu_structure,
            contraindications, conditions, confidence_score, status, version
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
        (
            diet_id, cmd.session_id, cmd.trace_id, cmd.source_url, cmd.content_sha256,
            cmd.diet_name,
            json.dumps(cmd.allowed_foods, ensure_ascii=False),
            json.dumps(cmd.forbidden_foods, ensure_ascii=False),
            json.dumps(cmd.menu_structure, ensure_ascii=False),
            json.dumps(cmd.contraindications, ensure_ascii=False),
            json.dumps(cmd.conditions, ensure_ascii=False),
            cmd.confidence_score, status.value,
        )
    )

    # Audit log
    await _audit(db, "diet_master", diet_id, "created",
                 new_value=json.dumps({"status": status.value, "issues": issues},
                                      ensure_ascii=False),
                 trace_id=cmd.trace_id)
    await db.commit()

    log.info("[%s] Diet registered: %s (status=%s, confidence=%.2f)",
             cmd.trace_id, diet_id, status.value, cmd.confidence_score)
    return diet_id, status


async def verify_diet(
    db: aiosqlite.Connection,
    diet_id: str,
    approved: bool,
    actor: str = "moderator",
    trace_id: str = "-",
) -> bool:
    """
    Moderator action: одобрение/отклонение диеты.
    OCC: проверяет статус перед обновлением.
    """
    async with db.execute(
        "SELECT id, status, version FROM diet_master WHERE id=?", (diet_id,)
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return False

    old_status = row["status"]
    new_status = DietStatus.APPROVED.value if approved else DietStatus.ARCHIVED.value
    now = datetime.utcnow().isoformat()

    # OCC: обновляем только если version совпадает
    result = await db.execute(
        """UPDATE diet_master SET status=?, version=version+1,
           is_verified=1, verified_by=?, verified_at=?, updated_at=?
           WHERE id=? AND version=?""",
        (new_status, actor, now, now, diet_id, row["version"])
    )
    if result.rowcount == 0:
        log.warning("[%s] OCC conflict on diet %s", trace_id, diet_id)
        return False

    await _audit(db, "diet_master", diet_id, "verified",
                 old_value=old_status, new_value=new_status,
                 actor=actor, trace_id=trace_id)
    await db.commit()
    log.info("[%s] Diet %s -> %s by %s", trace_id, diet_id, new_status, actor)
    return True


async def get_diet_by_id(db: aiosqlite.Connection, diet_id: str) -> Optional[dict]:
    async with db.execute(
        "SELECT * FROM diet_master WHERE id=?", (diet_id,)
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    return _row_to_dict(row)


async def search_diets(
    db: aiosqlite.Connection,
    query: str = "",
    status: str = DietStatus.APPROVED.value,
    limit: int = 20,
    offset: int = 0,
) -> list:
    if query:
        sql = """SELECT * FROM diet_master WHERE status=?
                 AND (diet_name LIKE ? OR conditions LIKE ? OR allowed_foods LIKE ?)
                 ORDER BY confidence_score DESC LIMIT ? OFFSET ?"""
        q = f"%{query}%"
        async with db.execute(sql, (status, q, q, q, min(limit, 100), offset)) as cur:
            rows = await cur.fetchall()
    else:
        sql = "SELECT * FROM diet_master WHERE status=? ORDER BY created_at DESC LIMIT ? OFFSET ?"
        async with db.execute(sql, (status, min(limit, 100), offset)) as cur:
            rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: aiosqlite.Row) -> dict:
    d = dict(row)
    for field in ["allowed_foods", "forbidden_foods", "menu_structure",
                  "contraindications", "conditions"]:
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                pass
    return d


async def _audit(
    db: aiosqlite.Connection,
    entity_type: str,
    entity_id: str,
    action: str,
    old_value: str = None,
    new_value: str = None,
    actor: str = "system",
    trace_id: str = "-",
) -> None:
    await db.execute(
        """INSERT INTO audit_log(id, entity_type, entity_id, action,
           actor, old_value, new_value, trace_id)
           VALUES(?,?,?,?,?,?,?,?)""",
        (str(uuid.uuid4()), entity_type, entity_id, action,
         actor, old_value, new_value, trace_id)
    )