"""Глобальная обработка ошибок: бот не падает, пользователю — понятный текст."""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import ExceptionTypeFilter
from aiogram.types import ErrorEvent

from bot.notion_repo import NotionError

log = logging.getLogger(__name__)


async def _reply(event: ErrorEvent, text: str) -> None:
    upd = event.update
    try:
        if upd.message:
            await upd.message.answer(text)
        elif upd.callback_query:
            await upd.callback_query.answer(text[:190], show_alert=True)
    except Exception:
        log.exception("Не удалось отправить сообщение об ошибке")


async def on_notion_error(event: ErrorEvent) -> None:
    await _reply(event, f"⚠️ {event.exception}")


async def on_any_error(event: ErrorEvent) -> None:
    log.error("Необработанная ошибка", exc_info=event.exception)
    await _reply(event, "⚠️ Что-то пошло не так. Подробности в логе.")


def register(router: Router) -> None:
    """Вешает обработчики на корневой роутер: ошибки всплывают от дочерних к родителю."""
    router.errors.register(on_notion_error, ExceptionTypeFilter(NotionError))
    router.errors.register(on_any_error)
