"""Доступ только для ALLOWED_USER_ID и работа без поля «Фокус на» (без сети)."""
import asyncio
import logging
from types import SimpleNamespace

import pytest

from bot.middlewares import AllowedUserMiddleware
from bot.notion_repo import NotionError, NotionRepo

ALLOWED = 111


def _run_middleware(user_id: int | None) -> bool:
    called = False

    async def handler(event, data):
        nonlocal called
        called = True

    mw = AllowedUserMiddleware(ALLOWED)
    user = SimpleNamespace(id=user_id) if user_id is not None else None
    asyncio.run(mw(handler, object(), {"event_from_user": user}))
    return called


def test_allowed_user_passes() -> None:
    assert _run_middleware(ALLOWED) is True


def test_foreign_user_ignored() -> None:
    assert _run_middleware(222) is False


def test_update_without_user_ignored() -> None:
    assert _run_middleware(None) is False


# ---------- схема Notion ----------

def _schema(with_focus: bool) -> dict:
    props = {
        "Task name": {"type": "title"},
        "Due": {"type": "date"},
        "Status": {"type": "status"},
        "Категория": {"type": "select", "select": {"options": [{"name": "Физика"}, {"name": "ТОЭ"}]}},
        "Раздел": {"type": "select", "select": {"options": [{"name": "🔥 Горит сейчас"}]}},
        "Заметки": {"type": "rich_text"},
    }
    if with_focus:
        props["Фокус на"] = {"type": "date"}
    return {"properties": props}


def _page(focus: str | None) -> dict:
    return {
        "object": "page",
        "id": "p1",
        "url": "",
        "properties": {
            "Task name": {"title": [{"plain_text": "Курсовая"}]},
            "Due": {"date": {"start": "2026-09-25T18:00:00.000+03:00"}},
            "Status": {"status": {"name": "In progress"}},
            "Категория": {"select": {"name": "Физика"}},
            "Раздел": {"select": None},
            "Заметки": {"rich_text": []},
            **({"Фокус на": {"date": {"start": focus}}} if focus else {}),
        },
    }


class FakeDataSources:
    def __init__(self, schema: dict, pages: list[dict]) -> None:
        self.schema, self.pages = schema, pages

    async def retrieve(self, **kwargs):
        return self.schema

    async def query(self, **kwargs):
        return {"results": self.pages, "has_more": False}


def _repo(schema: dict, pages: list[dict]) -> NotionRepo:
    repo = NotionRepo("fake-token", "ds")
    repo._client = SimpleNamespace(data_sources=FakeDataSources(schema, pages))
    return repo


def test_without_focus_field_works_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    repo = _repo(_schema(with_focus=False), [_page(None)])
    with caplog.at_level(logging.WARNING, logger="bot.notion_repo"):
        tasks = asyncio.run(repo.open_tasks())
    assert repo.has_focus_field is False
    assert any("Фокус на" in r.getMessage() for r in caplog.records)
    assert tasks[0].title == "Курсовая" and tasks[0].focus_on is None


def test_with_focus_field_parses_task() -> None:
    repo = _repo(_schema(with_focus=True), [_page("2026-09-19")])
    (task,) = asyncio.run(repo.open_tasks())
    assert repo.has_focus_field is True
    assert str(task.focus_on) == "2026-09-19"
    assert task.due_datetime is not None and task.due_datetime.hour == 18
    assert task.category == "Физика" and task.section is None


def test_select_options_loaded_from_schema() -> None:
    repo = _repo(_schema(with_focus=True), [])
    asyncio.run(repo.check_schema())
    assert repo.categories == ("Физика", "ТОЭ")
    assert repo.sections == ("🔥 Горит сейчас",)


def test_missing_required_field_is_error() -> None:
    schema = _schema(with_focus=True)
    del schema["properties"]["Status"]
    with pytest.raises(NotionError):
        asyncio.run(_repo(schema, []).check_schema())
