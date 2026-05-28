"""Logger с Correlation ID поддержкой."""
import logging
import sys
from contextvars import ContextVar
from typing import Optional

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")
_session_id_var: ContextVar[str] = ContextVar("session_id", default="-")


def set_trace_context(trace_id: str, session_id: str = "-") -> None:
    _trace_id_var.set(trace_id)
    _session_id_var.set(session_id)


def get_trace_id() -> str:
    return _trace_id_var.get()


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = _trace_id_var.get()
        record.session_id = _session_id_var.get()
        return True


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [trace=%(trace_id)s] "
            "[session=%(session_id)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        handler.addFilter(CorrelationFilter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger