"""Клавиатуры бота."""
from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_TODAY = "📅 Сегодня"
BTN_TOMORROW = "🌙 Завтра"
BTN_DEADLINES = "⏰ Дедлайны"
BTN_OVERDUE = "❗ Просрочено"
BTN_CATEGORIES = "🗂 Категории"

MAIN_BUTTONS = (BTN_TODAY, BTN_TOMORROW, BTN_DEADLINES, BTN_OVERDUE, BTN_CATEGORIES)


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_TODAY), KeyboardButton(text=BTN_TOMORROW)],
            [KeyboardButton(text=BTN_DEADLINES), KeyboardButton(text=BTN_OVERDUE)],
            [KeyboardButton(text=BTN_CATEGORIES)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Напиши задачу свободным текстом…",
    )
