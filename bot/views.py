"""Сборка сообщений-списков по короткому коду вида.

Код зашит в callback_data кнопок статусов, чтобы после нажатия перерисовать
то же самое сообщение:
  t — сегодня, m — завтра, w — дедлайны на неделю, o — просрочено,
  c<N> — категория N, M<ггммдд> — утренняя сводка, E<ггммдд> — вечерняя (на дату).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import formatters
from bot.config import now as now_msk
from bot.models import STATUS_IN_PROGRESS, Task
from bot.notion_repo import NotionRepo
from bot.schedule import Schedule


def date_code(prefix: str, d: date) -> str:
    return f"{prefix}{d:%y%m%d}"


def _code_date(code: str) -> date:
    return datetime.strptime(code[1:], "%y%m%d").date()


def lessons_text(schedule: Schedule, d: date) -> str:
    return formatters.lessons_block(schedule.lessons_for(d), schedule.week_letter(d))


def build_view(
    code: str,
    tasks: list[Task],
    repo: NotionRepo,
    schedule: Schedule,
    now: datetime | None = None,
) -> formatters.Numbered:
    n = now or now_msk()
    focus = repo.has_focus_field
    if code == "t":
        d = n.date()
        return formatters.day_view("📅 Сегодня", d, tasks, n, focus, lessons_text(schedule, d))
    if code == "m":
        d = n.date() + timedelta(days=1)
        return formatters.day_view("🌙 Завтра", d, tasks, n, focus, lessons_text(schedule, d))
    if code == "w":
        return formatters.deadlines_view(tasks, n)
    if code == "o":
        return formatters.overdue_view(tasks, n)
    if code.startswith("c"):
        return formatters.category_view(tasks, repo.categories[int(code[1:])], n)
    if code.startswith("M"):
        d = _code_date(code)
        return formatters.morning_view(d, tasks, n, focus, lessons_text(schedule, d))
    if code.startswith("E"):
        d = _code_date(code)
        return formatters.evening_view(d, tasks, n, focus, lessons_text(schedule, d))
    raise ValueError(f"unknown view code {code!r}")


def status_keyboard(tasks: list[Task], code: str) -> InlineKeyboardMarkup | None:
    """callback_data: «s:<p|d>:<page_id без дефисов>:<код>» — до 45 байт при лимите 64."""
    rows = []
    for i, t in enumerate(tasks, start=1):
        pid = t.id.replace("-", "")
        row = []
        if t.status != STATUS_IN_PROGRESS:
            row.append(InlineKeyboardButton(text=f"{i}. ▶️ В работу", callback_data=f"s:p:{pid}:{code}"))
        row.append(InlineKeyboardButton(text=f"{i}. ✅ Готово", callback_data=f"s:d:{pid}:{code}"))
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
