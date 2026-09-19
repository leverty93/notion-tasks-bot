"""/start и /help."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.keyboards import main_keyboard

router = Router(name="common")

HELP_TEXT = (
    "👋 Я твой бот задач из Notion.\n\n"
    "📅 /today — пары, тройка и дедлайны на сегодня\n"
    "🌙 /tomorrow — то же на завтра\n"
    "⏰ /deadlines — дедлайны на 7 дней\n"
    "❗ /overdue — просроченное\n"
    "🗂 /cat — задачи по категории\n"
    "➕ /add название | ДД.ММ — быстро добавить задачу\n\n"
    "Или просто напиши задачу обычным текстом."
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_keyboard())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_keyboard())
