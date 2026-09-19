"""Доменные модели, не зависящие от Notion API."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

STATUS_NOT_STARTED = "Not started"
STATUS_IN_PROGRESS = "In progress"
STATUS_DONE = "Done"
STATUS_ARCHIVED = "Archived"
OPEN_STATUSES = (STATUS_NOT_STARTED, STATUS_IN_PROGRESS)

CATEGORIES = (
    "Физика",
    "Инженерная графика",
    "Учёба (прочее)",
    "Личное",
    "Деньги/карьера",
    "Хобби/проекты",
    "Организация",
    "Математический анализ",
    "ТОЭ",
    "Физкультура",
)

SECTIONS = (
    "🔥 Горит сейчас",
    "📚 Фоновая тема семестра",
    "💰 Деньги/проекты",
    "🛠 Проекты для души",
    "🌏 Опционально",
    "🎯 Дальний ящик",
    "⚙️ Организация",
)


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    status: str | None
    due_date: date | None = None
    due_datetime: datetime | None = None  # задан, если у Due есть время (aware, MSK)
    category: str | None = None
    section: str | None = None
    notes: str = ""
    focus_on: date | None = None
    url: str = ""

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    def is_overdue(self, now: datetime) -> bool:
        """Просрочена: дата раньше сегодня, либо время Due уже прошло."""
        if not self.is_open or self.due_date is None:
            return False
        if self.due_datetime is not None:
            return self.due_datetime < now
        return self.due_date < now.date()


@dataclass(frozen=True)
class NewTask:
    title: str
    due_date: date | None = None
    due_datetime: datetime | None = None
    category: str | None = None
    section: str | None = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "due_datetime": self.due_datetime.isoformat() if self.due_datetime else None,
            "category": self.category,
            "section": self.section,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NewTask":
        return cls(
            title=d["title"],
            due_date=date.fromisoformat(d["due_date"]) if d.get("due_date") else None,
            due_datetime=datetime.fromisoformat(d["due_datetime"]) if d.get("due_datetime") else None,
            category=d.get("category"),
            section=d.get("section"),
            notes=d.get("notes") or "",
        )
