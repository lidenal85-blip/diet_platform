"""Diet Extractor: ядро Leviathan LLMFactory (gemini-2.5-flash, KeyPool, CircuitBreaker) + fallback.

Подключён к /opt/leviathan_engine/llm_factory.py — использует KeyPool с 14 ключами,
CircuitBreaker и авто-фоллбэк на Groq при исчерпании Gemini.
Агент управляет Diet Platform; Diet Platform агентом не пользуется.
"""
import json
import re
import sys
import uuid
from typing import Optional

# Путь к ядру Leviathan — приоритетный import
sys.path.insert(0, "/opt/leviathan_engine")
try:
    from llm_factory import LLMFactory
    _LEVIATHAN_CORE = True
except ImportError:
    _LEVIATHAN_CORE = False

from building_blocks.config import get_settings
from building_blocks.contracts import SubmitDietDraftCommand
from building_blocks.logger import get_logger
from modules.diet_extractor.sanitizer.text_sanitizer import sanitize_text

log = get_logger(__name__)
cfg = get_settings()

if _LEVIATHAN_CORE:
    log.info("🔗 Leviathan LLMFactory (gemini-2.5-flash, KeyPool 14 ключей) подключён")
else:
    log.warning("⚠️ LLMFactory недоступен, fallback на google.genai")

MODEL = "gemini-2.5-flash"

EXTRACTION_SYSTEM = """\
Ты — медицинский NLP-парсер диет и планов питания.
ВОЗВРАЩАЙ ТОЛЬКО ВАЛИДНЫЙ JSON БЕЗ ПОЯСНЕНИЙ, БЕЗ МАРКДАУНА.
"""

EXTRACTION_PROMPT = """\
Извлечи информацию о диете из текста ниже.

Обязательная схема ответа:
{
  "diet_name": "string",
  "allowed_foods": ["string"],
  "forbidden_foods": ["string"],
  "menu_structure": {
    "breakfast": ["string"],
    "lunch":     ["string"],
    "dinner":    ["string"],
    "snacks":    ["string"]
  },
  "contraindications": ["string"],
  "conditions":        ["string"],
  "confidence_score":  0.0
}

Правила:
- confidence_score 0.0–1.0: < 0.4 если недостаточно данных
- Не выдумывай данные которых нет в тексте
- allowed_foods / forbidden_foods — конкретные продукты

Текст:
{text}
"""


def _heuristic_extract(text: str) -> dict:
    """Fallback: эвристика без LLM."""
    allowed, forbidden = [], []
    for line in text.split("."):
        line = line.strip()
        if any(m in line.lower() for m in ["можно", "разрешено", "рекомендуется"]) and len(line) < 200:
            allowed.append(line[:100])
        elif any(m in line.lower() for m in ["нельзя", "запрещено", "исключить"]) and len(line) < 200:
            forbidden.append(line[:100])
    m = re.search(r"(диета|питание|рацион)\s+([\w\s]{3,40})", text, re.IGNORECASE)
    diet_name = m.group(0)[:50] if m else "Неизвестная диета"
    score = min(0.35, (len(allowed) + len(forbidden)) * 0.05)
    return {
        "diet_name": diet_name,
        "allowed_foods": allowed[:20],
        "forbidden_foods": forbidden[:20],
        "menu_structure": {"breakfast": [], "lunch": [], "dinner": [], "snacks": []},
        "contraindications": [],
        "conditions": [],
        "confidence_score": score,
    }


async def _llm_extract(clean_text: str, trace_id: str) -> Optional[dict]:
    """LLM экстракция: Leviathan LLMFactory (KeyPool+CB) или fallback google.genai."""
    prompt = EXTRACTION_PROMPT.format(text=clean_text[:8000])

    # ── Приоритет 1: Leviathan Core LLMFactory ──────────────────
    if _LEVIATHAN_CORE:
        try:
            raw = await LLMFactory.execute_request(
                prompt=prompt,
                system=EXTRACTION_SYSTEM,
                model=MODEL,
                driver="gemini",
                fallback=True,
                task_type="structured",
            )
            raw = re.sub(r"^```(?:json)?\n?", "", raw.strip())
            raw = re.sub(r"\n?```$", "", raw)
            result = json.loads(raw)
            log.info("[%s] Leviathan LLMFactory OK: %s conf=%.2f",
                     trace_id, result.get("diet_name", "?"), result.get("confidence_score", 0))
            return result
        except json.JSONDecodeError as e:
            log.warning("[%s] JSON parse error from LLMFactory: %s", trace_id, e)
            return None
        except Exception as e:
            log.error("[%s] LLMFactory error: %s", trace_id, e)
            # Провалился — падаем на heuristic в extract_diet
            return None

    # ── Fallback: google.genai (direct) ───────────────────────────
    try:
        import itertools
        from google import genai as _genai
        from google.genai import types as _types

        keys: list[str] = []
        raw_keys = getattr(cfg, 'gemini_keys', '') or ''
        for k in raw_keys.split(','):
            k = k.strip()
            if k:
                keys.append(k)
        single = getattr(cfg, 'gemini_api_key', '') or ''
        if single and single not in keys:
            keys.append(single)

        for api_key in keys[:3]:
            try:
                client = _genai.Client(api_key=api_key)
                full_prompt = EXTRACTION_SYSTEM + "\n" + prompt
                response = client.models.generate_content(
                    model=MODEL, contents=full_prompt,
                    config=_types.GenerateContentConfig(temperature=0.1, max_output_tokens=2048),
                )
                raw = response.text.strip()
                raw = re.sub(r"^```(?:json)?\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
                result = json.loads(raw)
                log.info("[%s] google.genai fallback OK conf=%.2f",
                         trace_id, result.get("confidence_score", 0))
                return result
            except Exception as e:
                if '429' in str(e) or 'RESOURCE_EXHAUSTED' in str(e):
                    continue
                log.error("[%s] google.genai error: %s", trace_id, e)
                break
    except ImportError:
        log.warning("[%s] google.genai not installed", trace_id)

    return None


async def extract_diet(
    raw_text: str, source_url: str, session_id: str,
    trace_id: str, content_sha256: str,
) -> Optional[SubmitDietDraftCommand]:
    clean_text, is_suspicious = sanitize_text(raw_text)
    if is_suspicious:
        log.warning("[%s] Suspicious content, sanitized", trace_id)

    extracted = await _llm_extract(clean_text, trace_id)

    if not extracted:
        log.info("[%s] Using heuristic fallback", trace_id)
        extracted = _heuristic_extract(clean_text)

    confidence = float(extracted.get("confidence_score", 0.0))
    if confidence < cfg.min_confidence_score:
        log.info("[%s] Low confidence %.2f < %.2f, skipping",
                 trace_id, confidence, cfg.min_confidence_score)
        return None

    return SubmitDietDraftCommand(
        draft_id=str(uuid.uuid4()), session_id=session_id, trace_id=trace_id,
        source_url=source_url, content_sha256=content_sha256,
        diet_name=extracted.get("diet_name", "Неизвестная диета")[:200],
        allowed_foods=extracted.get("allowed_foods", [])[:50],
        forbidden_foods=extracted.get("forbidden_foods", [])[:50],
        menu_structure=extracted.get("menu_structure", {}),
        contraindications=extracted.get("contraindications", [])[:30],
        conditions=extracted.get("conditions", [])[:30],
        confidence_score=confidence,
        raw_text_excerpt=clean_text[:500],
    )