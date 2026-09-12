"""planner.tz — минимальный timezone/calendar helper (ADR-6, PATCH-7).

Контракт (подтверждён владельцем 2026-09-12):
- ``user_profiles.timezone`` — канонический timezone пользователя;
- ``Europe/Moscow`` — fallback для legacy/unknown пользователей (НЕ универсальная tz);
- **Phase 0:** tz используется ТОЛЬКО для календарной семантики
  (weekly_plans.start_date/end_date, meal_state.day_date, определение «сегодня»);
- **Phase 1:** дополнительно scheduler/reminders/локальное время уведомлений
  (здесь НЕ реализуется — см. ADR-4/PATCH-8);
- инвариант PATCH-10: события — UTC (абсолютное время), meal_state.day_date —
  локальная календарная дата пользователя; «сегодня» никогда не выводится из ts.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Europe/Moscow"

__all__ = [
    "DEFAULT_TZ",
    "TimezoneError",
    "WeekBoundsError",
    "get_user_tz",
    "now_utc",
    "today_local",
    "to_local_date",
    "date_to_str",
    "str_to_date",
    "week_bounds",
    "validate_week_dates",
    "day_date_for",
    "utc_ts_string",
]


class TimezoneError(ValueError):
    """Некорректное имя timezone (не должно молча заменяться)."""


class WeekBoundsError(ValueError):
    """Нарушение календарного инварианта end_date = start_date + 6 дней."""


def get_user_tz(timezone_name: str | None) -> ZoneInfo:
    """ZoneInfo пользователя; fallback Europe/Moscow для legacy/unknown (ADR-6)."""
    name = (timezone_name or "").strip() or DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except Exception as exc:  # неизвестное имя зоны — это ошибка данных, не молчаливый МСК
        raise TimezoneError(f"unknown timezone {timezone_name!r}") from exc


def now_utc() -> datetime:
    """Абсолютное время события (для events.ts). Всегда UTC."""
    return datetime.now(tz=timezone.utc)


def utc_ts_string(moment: datetime | None = None) -> str:
    """UTC-строка времени в формате SQLite datetime('now'): 'YYYY-MM-DD HH:MM:SS'."""
    dt = moment.astimezone(timezone.utc) if moment else now_utc()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def today_local(timezone_name: str | None) -> date:
    """«Сегодня» в timezone пользователя (канонический источник day_date)."""
    return datetime.now(tz=get_user_tz(timezone_name)).date()


def to_local_date(moment_utc: datetime, timezone_name: str | None) -> date:
    """Локальная календарная дата пользователя для данного UTC-момента."""
    if moment_utc.tzinfo is None:
        raise TimezoneError("naive datetime is not allowed (must be UTC-aware)")
    return moment_utc.astimezone(get_user_tz(timezone_name)).date()


def date_to_str(d: date) -> str:
    """ISO 'YYYY-MM-DD' — формат хранения weekly_plans/meal_state дат."""
    return d.isoformat()


def str_to_date(s: str) -> date:
    """Парсинг ISO 'YYYY-MM-DD'; мусор → ValueError (не молча)."""
    return date.fromisoformat(str(s).strip())


def week_bounds(start_date: date) -> tuple[date, date]:
    """Границы недели: (start_date, start_date + 6 дней) — PATCH-1."""
    return start_date, start_date + timedelta(days=6)


def validate_week_dates(start_date: date, end_date: date) -> None:
    """Инвариант календарной недели (PATCH-1); нарушение → WeekBoundsError."""
    expected_start, expected_end = week_bounds(start_date)
    if end_date != expected_end or start_date != expected_start:
        raise WeekBoundsError(
            f"end_date {end_date} must be start_date {start_date} + 6 days "
            f"(expected {expected_end})"
        )


def day_date_for(plan_start_date: date, day_index: int) -> date:
    """Календарная дата дня плана: start_date + day_index (0-based), в tz пользователя."""
    if day_index < 0 or day_index > 6:
        raise WeekBoundsError(f"day_index {day_index} outside 0..6")
    return plan_start_date + timedelta(days=day_index)
