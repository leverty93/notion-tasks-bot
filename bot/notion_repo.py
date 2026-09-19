"""Весь доступ к Notion. Остальной код работает только с bot.models.

Используется Notion API 2025-09-03 (notion-client 3.x): задачи читаются через
POST /v1/data_sources/{data_source_id}/query, а не через устаревший
/v1/databases/{id}/query.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Any

from notion_client import AsyncClient
from notion_client.errors import APIResponseError, NotionClientErrorBase

from bot.config import TZ
from bot.models import (
    CATEGORIES,
    SECTIONS,
    STATUS_ARCHIVED,
    STATUS_DONE,
    STATUS_NOT_STARTED,
    NewTask,
    Task,
)

log = logging.getLogger(__name__)

P_TITLE = "Task name"
P_DUE = "Due"
P_STATUS = "Status"
P_CATEGORY = "Категория"
P_SECTION = "Раздел"
P_NOTES = "Заметки"
P_FOCUS = "Фокус на"

_REQUIRED = {P_TITLE: "title", P_DUE: "date", P_STATUS: "status"}
_OPTIONAL = {P_CATEGORY: "select", P_SECTION: "select", P_NOTES: "rich_text"}


class NotionError(RuntimeError):
    """Понятная пользователю ошибка Notion (детали — в логе)."""


OPTIONS_MAX_AGE_S = 600  # как часто перечитывать варианты select из схемы


class NotionRepo:
    def __init__(self, token: str, data_source_id: str) -> None:
        self._client = AsyncClient(auth=token, timeout_ms=20_000)
        self._ds_id = data_source_id
        self._schema_checked = False
        self._schema_at = 0.0
        self.has_focus_field = False
        # Допустимые значения select. Берутся из схемы Notion; список в коде — запасной.
        self.categories: tuple[str, ...] = CATEGORIES
        self.sections: tuple[str, ...] = SECTIONS

    async def close(self) -> None:
        await self._client.aclose()

    # ---------- схема ----------

    async def check_schema(self) -> None:
        ds = await self._call(self._client.data_sources.retrieve, data_source_id=self._ds_id)
        props: dict[str, Any] = ds.get("properties", {})
        types = {name: p.get("type") for name, p in props.items()}
        first = not self._schema_checked

        for name, typ in _REQUIRED.items():
            if types.get(name) != typ:
                raise NotionError(f"В базе нет обязательного поля «{name}» ({typ}).")
        for name, typ in _OPTIONAL.items():
            if types.get(name) != typ and first:
                log.warning("Поле «%s» (%s) не найдено в базе — оно будет пустым", name, typ)

        has_focus = types.get(P_FOCUS) == "date"
        if not has_focus and (first or self.has_focus_field):
            log.warning("Поле «%s» (date) не найдено — блок «тройка» отключён", P_FOCUS)
        self.has_focus_field = has_focus

        categories = _select_options(props.get(P_CATEGORY))
        sections = _select_options(props.get(P_SECTION))
        if categories and categories != self.categories:
            log.info("Категории из Notion: %s", ", ".join(categories))
            self.categories = categories
        if sections and sections != self.sections:
            log.info("Разделы из Notion: %s", ", ".join(sections))
            self.sections = sections

        self._schema_checked = True
        self._schema_at = time.monotonic()
        if first:
            log.info("Схема Notion проверена, полей: %d, «%s»: %s", len(props), P_FOCUS, has_focus)

    async def _ensure_schema(self) -> None:
        if not self._schema_checked:
            await self.check_schema()

    async def refresh_options(self) -> None:
        """Перечитать схему, если она старше OPTIONS_MAX_AGE_S. Ошибки не мешают работе."""
        if self._schema_checked and time.monotonic() - self._schema_at < OPTIONS_MAX_AGE_S:
            return
        try:
            await self.check_schema()
        except NotionError as e:
            log.warning("Не удалось обновить варианты из схемы, использую прежние: %s", e)

    # ---------- чтение ----------

    async def open_tasks(self) -> list[Task]:
        """Все задачи, кроме Done и Archived."""
        await self._ensure_schema()
        flt = {
            "and": [
                {"property": P_STATUS, "status": {"does_not_equal": STATUS_DONE}},
                {"property": P_STATUS, "status": {"does_not_equal": STATUS_ARCHIVED}},
            ]
        }
        pages = await self._query_all(filter=flt)
        return [self._to_task(p) for p in pages]

    async def _query_all(self, **body: Any) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            kwargs = dict(body, page_size=100)
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = await self._call(
                self._client.data_sources.query, data_source_id=self._ds_id, **kwargs
            )
            results.extend(r for r in resp["results"] if r.get("object") == "page")
            if not resp.get("has_more"):
                return results
            cursor = resp.get("next_cursor")

    # ---------- запись ----------

    async def set_status(self, page_id: str, status: str) -> Task:
        page = await self._call(
            self._client.pages.update,
            page_id=page_id,
            properties={P_STATUS: {"status": {"name": status}}},
        )
        return self._to_task(page)

    async def create_task(self, task: NewTask) -> Task:
        props: dict[str, Any] = {
            P_TITLE: {"title": [{"text": {"content": task.title[:2000]}}]},
            P_STATUS: {"status": {"name": STATUS_NOT_STARTED}},
        }
        if task.due_datetime is not None:
            props[P_DUE] = {"date": {"start": task.due_datetime.isoformat()}}
        elif task.due_date is not None:
            props[P_DUE] = {"date": {"start": task.due_date.isoformat()}}
        if task.category:
            props[P_CATEGORY] = {"select": {"name": task.category}}
        if task.section:
            props[P_SECTION] = {"select": {"name": task.section}}
        if task.notes:
            props[P_NOTES] = {"rich_text": [{"text": {"content": task.notes[:2000]}}]}
        page = await self._call(
            self._client.pages.create,
            parent={"type": "data_source_id", "data_source_id": self._ds_id},
            properties=props,
        )
        log.info("Создана задача в Notion: id=%s", page.get("id"))
        return self._to_task(page)

    # ---------- преобразование ----------

    def _to_task(self, page: dict[str, Any]) -> Task:
        pr = page.get("properties", {})
        due_date, due_dt = _parse_date(pr.get(P_DUE))
        focus = None
        if self.has_focus_field:
            focus, _ = _parse_date(pr.get(P_FOCUS))
        status = (pr.get(P_STATUS, {}).get("status") or {}).get("name")
        return Task(
            id=page["id"],
            title=_plain(pr.get(P_TITLE, {}).get("title")) or "Без названия",
            status=status,
            due_date=due_date,
            due_datetime=due_dt,
            category=_select(pr.get(P_CATEGORY)),
            section=_select(pr.get(P_SECTION)),
            notes=_plain(pr.get(P_NOTES, {}).get("rich_text")),
            focus_on=focus,
            url=page.get("url", ""),
        )

    # ---------- ошибки ----------

    async def _call(self, fn: Any, **kwargs: Any) -> Any:
        try:
            return await fn(**kwargs)
        except APIResponseError as e:
            log.error("Notion API error: code=%s status=%s msg=%s", e.code, e.status, e)
            if e.status in (401, 403):
                raise NotionError("Notion отклонил токен — проверь NOTION_TOKEN.") from e
            if e.status == 404:
                raise NotionError("Notion не видит базу — подключи интеграцию к базе (Connections).") from e
            if e.status == 429:
                raise NotionError("Notion просит подождать (лимит запросов). Попробуй через минуту.") from e
            raise NotionError("Notion вернул ошибку. Подробности в логе.") from e
        except NotionClientErrorBase as e:
            log.error("Notion client error: %r", e)
            raise NotionError("Не удалось связаться с Notion (таймаут/сеть).") from e
        except Exception as e:  # сеть, httpx и т.п.
            log.exception("Unexpected Notion error")
            raise NotionError("Не удалось связаться с Notion.") from e


def _plain(rich: list[dict[str, Any]] | None) -> str:
    return "".join(r.get("plain_text", "") for r in rich or []).strip()


def _select_options(prop: dict[str, Any] | None) -> tuple[str, ...]:
    if not prop or prop.get("type") != "select":
        return ()
    return tuple(o["name"] for o in prop["select"].get("options", []) if o.get("name"))


def _select(prop: dict[str, Any] | None) -> str | None:
    sel = (prop or {}).get("select")
    return sel.get("name") if sel else None


def _parse_date(prop: dict[str, Any] | None) -> tuple[date | None, datetime | None]:
    """Возвращает (дата, datetime в MSK или None, если время не указано)."""
    d = (prop or {}).get("date")
    if not d or not d.get("start"):
        return None, None
    start: str = d["start"]
    if "T" not in start:
        return date.fromisoformat(start), None
    dt = datetime.fromisoformat(start)
    dt = dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)
    return dt.date(), dt
