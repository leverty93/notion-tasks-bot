"""Отбор и сортировка задач (чистые функции, без обращений к API)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable

from bot.models import Task


def sort_key(t: Task) -> tuple:
    """По дате Due; без времени — в конце дня; без Due — в самом конце."""
    if t.due_date is None:
        return (date.max, time.max, t.title.lower())
    tm = t.due_datetime.time() if t.due_datetime else time.max
    return (t.due_date, tm, t.title.lower())


def _open(tasks: Iterable[Task]) -> list[Task]:
    return [t for t in tasks if t.is_open]


def focus_for(tasks: Iterable[Task], day: date) -> list[Task]:
    """«Тройка дня»: открытые задачи с «Фокус на» = day."""
    return sorted((t for t in _open(tasks) if t.focus_on == day), key=sort_key)


def due_between(tasks: Iterable[Task], start: date, end: date) -> list[Task]:
    """Открытые задачи с Due в [start; end] включительно."""
    return sorted(
        (t for t in _open(tasks) if t.due_date and start <= t.due_date <= end),
        key=sort_key,
    )


def due_on(tasks: Iterable[Task], day: date) -> list[Task]:
    return due_between(tasks, day, day)


def overdue(tasks: Iterable[Task], now: datetime) -> list[Task]:
    return sorted((t for t in tasks if t.is_overdue(now)), key=sort_key)


def by_category(tasks: Iterable[Task], category: str) -> list[Task]:
    return sorted((t for t in _open(tasks) if t.category == category), key=sort_key)


def week_range(today: date, days: int = 7) -> tuple[date, date]:
    return today, today + timedelta(days=days)
