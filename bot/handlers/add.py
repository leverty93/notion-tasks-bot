"""Добавление задач: /add (простой парсер) и свободный текст (LLM).

Черновик хранится в FSM-данных под id сообщения-карточки.
В Notion задача пишется только по кнопке «Сохранить».
"""
from __future__ import annotations

import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import formatters
from bot.add_parser import ADD_USAGE, AddParseError, parse_add
from bot.config import now
from bot.llm_parser import LLMError, LLMParser
from bot.models import NewTask
from bot.notion_repo import NotionRepo

log = logging.getLogger(__name__)
router = Router(name="add")


def card_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💾 Сохранить", callback_data="add:save"),
                InlineKeyboardButton(text="✏️ Изменить", callback_data="add:edit"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="add:cancel"),
            ]
        ]
    )


async def _show_card(
    message: Message,
    state: FSMContext,
    task: NewTask,
    warnings: list[str],
    source: str,
    placeholder: Message | None = None,
) -> None:
    text = formatters.task_card(task, warnings)
    if placeholder is not None:
        await placeholder.edit_text(text, reply_markup=card_keyboard())
        card = placeholder
    else:
        card = await message.answer(text, reply_markup=card_keyboard())
    data = await state.get_data()
    drafts = dict(data.get("drafts", {}))
    drafts[str(card.message_id)] = {"task": task.to_dict(), "warnings": warnings, "source": source}
    await state.update_data(drafts=drafts)


async def _pop_draft(state: FSMContext, message_id: int) -> dict | None:
    data = await state.get_data()
    drafts = dict(data.get("drafts", {}))
    draft = drafts.pop(str(message_id), None)
    await state.update_data(drafts=drafts)
    return draft


# ---------- /add ----------

@router.message(Command("add"))
async def cmd_add(message: Message, command: CommandObject, state: FSMContext) -> None:
    args = command.args or ""
    if not args.strip():
        await message.answer(ADD_USAGE)
        return
    try:
        task = parse_add(args, now().date())
    except AddParseError as e:
        await message.answer(f"⚠️ {e}\n\n{ADD_USAGE}")
        return
    await _show_card(message, state, task, [], source=f"/add {args}")


# ---------- неизвестные команды ----------

@router.message(F.text.startswith("/"))
async def unknown_command(message: Message) -> None:
    await message.answer("Не знаю такой команды. /help — список команд.")


# ---------- свободный текст → LLM ----------

@router.message(F.text)
async def free_text(message: Message, state: FSMContext, llm: LLMParser, repo: NotionRepo) -> None:
    text = message.text.strip()
    placeholder = await message.answer("🤖 Разбираю задачу…")
    try:
        await repo.refresh_options()
        task, warnings = await llm.parse(text, now(), repo.categories, repo.sections)
    except LLMError as e:
        await placeholder.edit_text(
            f"🤖 {e} Не получилось разобрать текст.\n\n"
            f"Добавь вручную:\n<code>/add {escape(text[:200])} | ДД.ММ</code>"
        )
        return
    await _show_card(message, state, task, warnings, source=text, placeholder=placeholder)


# ---------- кнопки карточки ----------

@router.callback_query(F.data == "add:save")
async def on_save(callback: CallbackQuery, state: FSMContext, repo: NotionRepo) -> None:
    draft = await _pop_draft(state, callback.message.message_id)
    if draft is None:
        await callback.answer("Черновик устарел — пришли задачу заново.", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        return
    task = NewTask.from_dict(draft["task"])
    try:
        await repo.create_task(task)
    except Exception:
        # Не потеряли черновик: вернём его, чтобы можно было нажать ещё раз.
        data = await state.get_data()
        drafts = dict(data.get("drafts", {}))
        drafts[str(callback.message.message_id)] = draft
        await state.update_data(drafts=drafts)
        raise
    await callback.answer("Сохранено")
    await callback.message.edit_text(
        formatters.task_card(task, header="✅ Сохранено в Notion"), reply_markup=None
    )


@router.callback_query(F.data == "add:edit")
async def on_edit(callback: CallbackQuery, state: FSMContext) -> None:
    draft = await _pop_draft(state, callback.message.message_id)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    text = "✏️ Пришли исправленный текст задачи."
    if draft and draft.get("source"):
        text += f"\n\nИсходный (нажми, чтобы скопировать):\n<code>{escape(draft['source'])}</code>"
    await callback.message.answer(text)


@router.callback_query(F.data == "add:cancel")
async def on_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await _pop_draft(state, callback.message.message_id)
    await callback.answer("Отменено")
    await callback.message.edit_text(
        callback.message.html_text + "\n\n❌ <i>Отменено</i>", reply_markup=None
    )
