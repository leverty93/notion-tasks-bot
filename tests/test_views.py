"""Тройка дня, дедлайны, просроченное, сводки — на данных как в тестовой базе."""
from datetime import date, datetime

import pytest

from bot import formatters, selectors
from bot.config import TZ
from bot.models import Task


def _dt(d: date, h: int = 12, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)


@pytest.fixture
def tasks() -> list[Task]:
    """Как в базе: только курсовая открыта, остальные задачи с «Фокус на» — Done."""
    return [
        Task("1", "Курсовая работа по инженерной графике", "In progress",
             category="Инженерная графика", focus_on=date(2026, 9, 19)),
        Task("2", "ДЗ по матану — Задание №2", "Done", focus_on=date(2026, 9, 20)),
        Task("3", "ТОЭ — ДЗ, задача 1.1.2.6", "Done", focus_on=date(2026, 9, 19)),
        Task("4", "KD — сборочный чертёж + спецификация", "Done", focus_on=date(2026, 9, 18)),
        Task("5", "Лаба по физике", "Not started", due_date=date(2026, 9, 19),
             due_datetime=_dt(date(2026, 9, 19), 18), category="Физика"),
        Task("6", "Старый долг", "Not started", due_date=date(2026, 9, 15)),
        Task("7", "Архивная", "Archived", due_date=date(2026, 9, 10), focus_on=date(2026, 9, 20)),
        Task("8", "Через 3 дня", "Not started", due_date=date(2026, 9, 22)),
        Task("9", "Через 5 дней", "Not started", due_date=date(2026, 9, 24)),
    ]


# ---------- тройка ----------

def test_focus_19_only_coursework(tasks: list[Task]) -> None:
    assert [t.id for t in selectors.focus_for(tasks, date(2026, 9, 19))] == ["1"]


def test_focus_20_empty_done_and_archived_excluded(tasks: list[Task]) -> None:
    assert selectors.focus_for(tasks, date(2026, 9, 20)) == []


def test_focus_18_done_excluded(tasks: list[Task]) -> None:
    assert selectors.focus_for(tasks, date(2026, 9, 18)) == []


def test_day_view_shows_focus(tasks: list[Task]) -> None:
    text = formatters.day_view("📅", date(2026, 9, 19), tasks, _dt(date(2026, 9, 19), 8), True).render()
    assert "Курсовая работа по инженерной графике" in text
    assert "ТОЭ — ДЗ" not in text  # Done
    assert formatters.NO_FOCUS not in text


def test_day_view_20_focus_not_chosen(tasks: list[Task]) -> None:
    text = formatters.day_view("📅", date(2026, 9, 20), tasks, _dt(date(2026, 9, 20), 8), True).render()
    assert formatters.NO_FOCUS in text
    assert "ДЗ по матану" not in text


def test_day_view_without_focus_field(tasks: list[Task]) -> None:
    """Поля «Фокус на» нет в базе → блока тройки нет, остальное работает."""
    text = formatters.day_view("📅", date(2026, 9, 19), tasks, _dt(date(2026, 9, 19), 8), False).render()
    assert "Тройка" not in text
    assert "Лаба по физике" in text


# ---------- дедлайны и просроченное ----------

def test_overdue_by_date_and_by_time(tasks: list[Task]) -> None:
    morning = _dt(date(2026, 9, 19), 8)
    evening = _dt(date(2026, 9, 19), 20)
    assert [t.id for t in selectors.overdue(tasks, morning)] == ["6"]
    # «Лаба» до 18:00 сегодня — в 20:00 уже просрочена; Archived не показывается
    assert [t.id for t in selectors.overdue(tasks, evening)] == ["6", "5"]


def test_deadlines_week_sorted_open_only(tasks: list[Task]) -> None:
    start, end = selectors.week_range(date(2026, 9, 19))
    assert [t.id for t in selectors.due_between(tasks, start, end)] == ["5", "8", "9"]


def test_sort_without_due_last() -> None:
    a = Task("a", "Без срока", "Not started")
    b = Task("b", "Со сроком", "Not started", due_date=date(2026, 9, 30))
    assert sorted([a, b], key=selectors.sort_key) == [b, a]


# ---------- сводки ----------

def test_morning_summary(tasks: list[Task]) -> None:
    d = date(2026, 9, 19)
    view = formatters.morning_view(d, tasks, _dt(d, 10), True, "🎓 пары")
    text = view.render()
    assert "🎓 пары" in text
    assert "Курсовая" in text                 # тройка
    assert "Через 3 дня" in text              # дедлайн через 3 дня входит
    assert "Через 5 дней" not in text         # через 5 — нет
    assert "❗ Просрочено" in text and "Старый долг" in text
    assert len(view.tasks) == len(set(view.tasks))  # без дублей в нумерации


def test_evening_summary_without_focus_shows_nearest(tasks: list[Task]) -> None:
    today = date(2026, 9, 19)
    text = formatters.evening_view(date(2026, 9, 20), tasks, _dt(today, 22, 30), True, None).render()
    assert "Тройка на завтра не выбрана" in text
    assert "Ближайшие дедлайны" in text
    assert "Через 3 дня" in text


def test_evening_summary_with_focus(tasks: list[Task]) -> None:
    text = formatters.evening_view(date(2026, 9, 19), tasks, _dt(date(2026, 9, 18), 22, 30), True, None).render()
    assert "Курсовая" in text
    assert "не выбрана" not in text
    assert "Дедлайны завтра" in text


def test_html_is_escaped() -> None:
    t = Task("x", "<b>Лаба</b> & отчёт", "Not started")
    assert "&lt;b&gt;Лаба&lt;/b&gt; &amp; отчёт" in formatters.task_line(1, t)
