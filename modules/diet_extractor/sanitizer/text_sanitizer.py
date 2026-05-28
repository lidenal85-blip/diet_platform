"""Data Sanitization Unit: защита от Prompt Injection + PII removal."""
import re
from building_blocks.logger import get_logger

log = get_logger(__name__)

# Паттерны промпт-инъекций
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(previous|all|prior|above)", re.IGNORECASE),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"forget\s+(your|all|previous)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now", re.IGNORECASE),
    re.compile(r"забудь|игнорируй|отменяешь", re.IGNORECASE),
    re.compile(r"предыдущие\s+инструкции", re.IGNORECASE),
    re.compile(r"system\s*:", re.IGNORECASE),
    re.compile(r"<\s*/?\s*(system|prompt|instruction)", re.IGNORECASE),
    re.compile(r"\[INST\]|\[/INST\]|<\|im_start\|>", re.IGNORECASE),
]

# PII паттерны
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")
_CARD_RE = re.compile(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b")

# Ограничение длины для LLM
MAX_TOKENS_APPROX = 8000  # ~32k chars


def sanitize_text(text: str) -> tuple[str, bool]:
    """
    Returns (sanitized_text, is_suspicious).
    is_suspicious=True если обнаружены паттерны инъекции.
    """
    is_suspicious = False

    # Проверяем injection patterns
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            log.warning("Injection pattern detected: %s", pattern.pattern)
            is_suspicious = True
            # Удаляем подозрительные строки
            text = pattern.sub("[REDACTED]", text)

    # PII removal
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _PHONE_RE.sub("[PHONE]", text)
    text = _CARD_RE.sub("[CARD]", text)

    # Ограничение длины
    text = text[:MAX_TOKENS_APPROX * 4]

    return text, is_suspicious