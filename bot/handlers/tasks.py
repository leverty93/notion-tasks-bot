"""Команды чтения (/today, /tomorrow, /deadlines, /overdue, /cat) и кнопки статусов."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.keyboards import BTN_CATEGORIES, BTN_DEADLINES, BTN_OVERDUE, BTN_TODAY, BTN_TOMORROW
from bot.models import STATUS_DONE, STATUS_IN_PROGRESS
from bot.notion_repo import NotionRepo
from bot.schedule import Schedule
from bot.views import build_view, status_keyboard

log = logging.getLogger(__name__)
router = Router(name="tasks")

ACTIONS = {"p": STATUS_IN_PROGRESS, "d": STATUS_DONE}


async def _show(message: Message, repo: NotionRepo, schedule: Schedule, code: str) -> None:
    view = build_view(code, await repo.open_tasks(), repo, schedule)
    await message.answer(
        view.render(),
        reply_markup=status_keyboard(view.tasks, code),
        disable_web_page_preview=True,
    )


@router.message(Command("today"))
@router.message(F.text == BTN_TODAY)
async def cmd_today(message: Message, repo: NotionRepo, schedule: Schedule) -> None:
    await _show(message, repo, schedule, "t")


@router.message(Command("tomorrow"))
@router.message(F.text == BTN_TOMORROW)
async def cmd_tomorrow(message: Message, repo: NotionRepo, schedule: Schedule) -> None:
    await _show(message, repo, schedule, "m")


@router.message(Command("deadlines"))
@router.message(F.text == BTN_DEADLINES)
async def cmd_deadlines(message: Message, repo: NotionRepo, schedule: Schedule) -> None:
    await _show(message, repo, schedule, "w")


@router.message(Command("overdue"))
@router.message(F.text == BTN_OVERDUE)
async def cmd_overdue(message: Message, repo: NotionRepo, schedule: Schedule) -> None:
    await _show(message, repo, schedule, "o")


def categories_keyboard(categories: tuple[str, ...]) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=c, callback_data=f"cat:{i}") for i, c in enumerate(categories)
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("cat"))
@router.message(F.text == BTN_CATEGORIES)
async def cmd_cat(message: Message, repo: NotionRepo) -> None:
    await repo.refresh_options()
    await message.answer("🗂 Выбери категорию:", reply_markup=categories_keyboard(repo.categories))


@router.callback_query(F.data.startswith("cat:"))
async def on_category(callback: CallbackQuery, repo: NotionRepo, schedule: Schedule) -> None:
    try:
        idx = int(callback.data.split(":", 1)[1])
        repo.categories[idx]
    except (ValueError, IndexError):
        await callback.answer("Неизвестная категория")
        return
    await callback.answer()
    await _show(callback.message, repo, schedule, f"c{idx}")


@router.callback_query(F.data.startswith("s:"))
async def on_status(callback: CallbackQuery, repo: NotionRepo, schedule: Schedule) -> None:
    try:
        _, action, pid, code = callback.data.split(":", 3)
        status = ACTIONS[action]
    except (ValueError, KeyError):
        await callback.answer("Кнопка устарела")
        return

    task = await repo.set_status(pid, status)
    label = "▶️ В работе" if status == STATUS_IN_PROGRESS else "✅ Готово"
    await callback.answer(f"{label}: {task.title}"[:190])

    # Перерисовываем исходное сообщение с актуальными данными.
    try:
        view = build_view(code, await repo.open_tasks(), repo, schedule)
    except (ValueError, IndexError):
        log.warning("Не удалось перерисовать вид %r", code)
        await callback.message.edit_reply_markup(reply_markup=None)
        return
    try:
        await callback.message.edit_text(
            view.render(),
            reply_markup=status_keyboard(view.tasks, code),
            disable_web_page_preview=True,
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
