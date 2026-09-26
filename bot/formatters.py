"""Тексты списков и сводок (HTML parse mode)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape

from bot import selectors
from bot.models import STATUS_IN_PROGRESS, NewTask, Task
from bot.schedule import Lesson

WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
NO_FOCUS = "Тройка не выбрана"
NEAREST_LIMIT = 5        # сколько ближайших дедлайнов показывать, если на нужный день их нет
MORNING_DEADLINE_DAYS = 3  # окно дедлайнов в утренней сводке


def fmt_date(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d:%d.%m}"


def fmt_due(t: Task, today: date | None = None) -> str:
    if t.due_date is None:
        return "без срока"
    if today is not None and t.due_date == today:
        label = "сегодня"
    elif today is not None and t.due_date == today + timedelta(days=1):
        label = "завтра"
    else:
        label = fmt_date(t.due_date)
    if t.due_datetime is not None:
        label += f" {t.due_datetime:%H:%M}"
    return label


def task_line(
    n: int | None, t: Task, today: date | None = None, show_due: bool = True, show_category: bool = True
) -> str:
    """Сначала строка с датой/категорией/статусом, под ней — название."""
    prefix = f"{n}. " if n is not None else "• "
    meta = []
    if show_due:
        meta.append(fmt_due(t, today))
    if show_category and t.category:
        meta.append(escape(t.category))
    if t.status == STATUS_IN_PROGRESS:
        meta.append("в работе")
    if meta:
        return f"{prefix}<i>{' · '.join(meta)}</i>\n{escape(t.title)}"
    return f"{prefix}{escape(t.title)}"


class Numbered:
    """Собирает текст, нумеруя задачи сквозь все блоки сообщения."""

    def __init__(self) -> None:
        self.tasks: list[Task] = []
        self.lines: list[str] = []

    def header(self, text: str) -> None:
        if self.lines:
            self.lines.append("")
        self.lines.append(f"<b>{text}</b>")

    def text(self, text: str) -> None:
        self.lines.append(text)

    def add(
        self,
        tasks: list[Task],
        today: date,
        empty: str | None = None,
        show_due: bool = True,
        show_category: bool = True,
    ) -> None:
        if not tasks and empty:
            self.lines.append(f"<i>{empty}</i>")
        for i, t in enumerate(tasks):
            if i:
                self.lines.append("")
            if t in self.tasks:  # одна задача может быть и в тройке, и в дедлайнах
                self.lines.append(task_line(self.tasks.index(t) + 1, t, today, show_due, show_category))
                continue
            self.tasks.append(t)
            self.lines.append(task_line(len(self.tasks), t, today, show_due, show_category))

    def render(self) -> str:
        return "\n".join(self.lines)


def day_view(
    title: str,
    day: date,
    tasks: list[Task],
    now: datetime,
    has_focus_field: bool,
    lessons_block: str | None = None,
) -> Numbered:
    """/today и /tomorrow: пары + тройка + дедлайны этого дня."""
    today = now.date()
    out = Numbered()
    out.header(f"{title}, {fmt_date(day)}")
    if lessons_block:
        out.lines.append("")
        out.text(lessons_block)
    if has_focus_field:
        out.header("🎯 Тройка дня")
        out.add(selectors.focus_for(tasks, day), today, empty=NO_FOCUS)
    add_deadlines(out, tasks, day, today)
    return out


def add_deadlines(
    out: "Numbered",
    tasks: list[Task],
    day: date,
    today: date,
    window: int = 0,
    header: str = "⏰ Дедлайны",
) -> None:
    """Дедлайны дня (или окна в window дней). Если их нет — ближайшие будущие."""
    end = day + timedelta(days=window)
    on_day = selectors.due_between(tasks, day, end)
    if on_day:
        out.header(header)
        out.add(on_day, today)
        return
    out.header("⏰ Ближайшие дедлайны")
    out.add(selectors.due_between(tasks, end, date.max)[:NEAREST_LIMIT], today, empty="Дедлайнов нет")


def deadlines_view(tasks: list[Task], now: datetime, days: int = 7) -> Numbered:
    today = now.date()
    start, end = selectors.week_range(today, days)
    out = Numbered()
    out.header(f"⏰ Дедлайны на {days} дней (до {fmt_date(end)})")
    out.add(selectors.due_between(tasks, start, end), today, empty="Дедлайнов нет 🎉")
    return out


def overdue_view(tasks: list[Task], now: datetime) -> Numbered:
    out = Numbered()
    out.header("❗ Просрочено")
    out.add(selectors.overdue(tasks, now), now.date(), empty="Ничего не просрочено 👍")
    return out


def category_view(tasks: list[Task], category: str, now: datetime) -> Numbered:
    out = Numbered()
    out.header(f"🗂 {escape(category)}")
    items = selectors.by_category(tasks, category)
    out.add(items, now.date(), empty="Открытых задач нет", show_category=False)
    return out


def task_card(task: NewTask, warnings: list[str] | None = None, header: str = "📝 Новая задача") -> str:
    """Карточка задачи перед сохранением."""
    if task.due_datetime is not None:
        due = f"{fmt_date(task.due_date)} {task.due_datetime:%H:%M}"
    elif task.due_date is not None:
        due = fmt_date(task.due_date)
    else:
        due = "—"
    lines = [
        f"<b>{header}</b>",
        "",
        f"<b>{escape(task.title)}</b>",
        f"Срок: {due}",
        f"Категория: {escape(task.category) if task.category else '—'}",
        f"Раздел: {escape(task.section) if task.section else '—'}",
    ]
    if task.notes:
        lines.append(f"Заметки: {escape(task.notes)}")
    for w in warnings or []:
        lines.append(f"⚠️ {escape(w)}")
    return "\n".join(lines)


# ---------- пары и сводки ----------

def lessons_block(lessons: list[Lesson], week_letter: str) -> str:
    lines = [f"<b>🎓 Пары</b> <i>(неделя {week_letter})</i>"]
    if not lessons:
        lines.append("<i>Пар нет</i>")
    for l in lessons:
        extra = [x for x in (l.kind, "онлайн" if l.online else "") if x]
        suffix = f" <i>· {' · '.join(extra)}</i>" if extra else ""
        lines.append(f"{l.start:%H:%M}–{l.end:%H:%M}  {escape(l.name)}{suffix}")
    return "\n".join(lines)


def morning_view(
    day: date, tasks: list[Task], now: datetime, has_focus_field: bool, lessons: str | None
) -> Numbered:
    """Утро: пары, тройка на сегодня, дедлайны сегодня…+3 дня, просроченное."""
    today = now.date()
    out = Numbered()
    out.header(f"☀️ Доброе утро! {fmt_date(day)}")
    if lessons:
        out.lines.append("")
        out.text(lessons)
    if has_focus_field:
        out.header("🎯 Тройка дня")
        out.add(selectors.focus_for(tasks, day), today, empty=NO_FOCUS)
    add_deadlines(
        out,
        tasks,
        day,
        today,
        window=MORNING_DEADLINE_DAYS,
        header=f"⏰ Дедлайны: сегодня и ближайшие {MORNING_DEADLINE_DAYS} дня",
    )
    late = [t for t in selectors.overdue(tasks, now) if t.due_date and t.due_date < day]
    if late:
        out.header("❗ Просрочено")
        out.add(late, today)
    return out


def evening_view(
    day: date, tasks: list[Task], now: datetime, has_focus_field: bool, lessons: str | None
) -> Numbered:
    """Вечер: пары завтра, тройка на завтра, дедлайны завтра (или ближайшие, если тройки нет)."""
    today = now.date()
    out = Numbered()
    out.header(f"🌙 План на завтра, {fmt_date(day)}")
    if lessons:
        out.lines.append("")
        out.text(lessons)
    focus = selectors.focus_for(tasks, day) if has_focus_field else []
    if has_focus_field:
        out.header("🎯 Тройка на завтра")
        if focus:
            out.add(focus, today)
        else:
            out.text("<i>Тройка на завтра не выбрана</i>")
    if has_focus_field and not focus:
        nearest = selectors.due_between(tasks, day, date.max)[:NEAREST_LIMIT]
        out.header("⏰ Ближайшие дедлайны")
        out.add(nearest, today, empty="Дедлайнов нет")
    else:
        add_deadlines(out, tasks, day, today, header="⏰ Дедлайны завтра")
    return out
