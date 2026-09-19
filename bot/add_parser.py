"""Простой парсер /add без LLM: «название | ДД.ММ[.ГГГГ] [ЧЧ:ММ]»."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from bot.config import TZ
from bot.models import NewTask

ADD_USAGE = (
    "Формат: <code>/add название | ДД.ММ</code>\n"
    "Можно с годом и временем: <code>/add Лаба | 25.09.2026 18:00</code>\n"
    "Без срока: <code>/add Купить тетради</code>"
)

_DATE_RE = re.compile(
    r"^(?P<d>\d{1,2})\.(?P<m>\d{1,2})(?:\.(?P<y>\d{2}|\d{4}))?"
    r"(?:\s+(?P<H>\d{1,2}):(?P<M>\d{2}))?$"
)

# Дата без года, оказавшаяся в прошлом больше чем на столько дней, переносится на след. год.
PAST_TOLERANCE_DAYS = 30


class AddParseError(ValueError):
    pass


def parse_add(text: str, today: date) -> NewTask:
    """text — всё, что после /add."""
    text = text.strip()
    if not text:
        raise AddParseError("Пустое название.")
    title, sep, when = text.partition("|")
    title = title.strip()
    if not title:
        raise AddParseError("Пустое название.")
    if not sep or not when.strip():
        return NewTask(title=title)

    m = _DATE_RE.match(when.strip())
    if not m:
        raise AddParseError("Не понял дату — нужно ДД.ММ, например 25.09.")
    day, month = int(m["d"]), int(m["m"])
    year = int(m["y"]) if m["y"] else today.year
    if m["y"] and year < 100:
        year += 2000
    try:
        due = date(year, month, day)
        if not m["y"] and due < today - timedelta(days=PAST_TOLERANCE_DAYS):
            due = due.replace(year=year + 1)
    except ValueError:
        raise AddParseError("Такой даты не бывает.") from None

    if m["H"] is None:
        return NewTask(title=title, due_date=due)
    hour, minute = int(m["H"]), int(m["M"])
    if hour > 23 or minute > 59:
        raise AddParseError("Не понял время — нужно ЧЧ:ММ, например 18:00.")
    dt = datetime(due.year, due.month, due.day, hour, minute, tzinfo=TZ)
    return NewTask(title=title, due_date=due, due_datetime=dt)
