"""Точка входа: python -m bot.main"""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from bot.config import ConfigError, load_settings
from bot.handlers import setup_routers
from bot.llm_parser import LLMParser
from bot.middlewares import AllowedUserMiddleware
from bot.notion_repo import NotionError, NotionRepo
from bot.schedule import Schedule, ScheduleError
from bot.summaries import Summaries

log = logging.getLogger("bot")

COMMANDS = [
    BotCommand(command="today", description="Сегодня"),
    BotCommand(command="tomorrow", description="Завтра"),
    BotCommand(command="deadlines", description="Дедлайны на 7 дней"),
    BotCommand(command="overdue", description="Просроченное"),
    BotCommand(command="cat", description="По категории"),
    BotCommand(command="add", description="Добавить: название | ДД.ММ"),
    BotCommand(command="help", description="Справка"),
]


async def run() -> None:
    settings = load_settings()
    logging.getLogger().setLevel(settings.log_level.upper())

    try:
        schedule = Schedule.load(settings.schedule_path, settings.week_a_monday)
    except ScheduleError as e:
        raise ConfigError(f"Ошибка в расписании — {e}") from None

    repo = NotionRepo(settings.notion_token.get_secret_value(), settings.notion_data_source_id)
    try:
        await repo.check_schema()
    except NotionError as e:
        # Не падаем: схема перепроверится при первом запросе.
        log.error("Проверка схемы Notion не удалась: %s", e)

    llm = LLMParser(
        settings.openrouter_api_key.get_secret_value() if settings.openrouter_api_key else None,
        settings.llm_base_url,
        settings.llm_model,
    )
    if not llm.enabled:
        log.warning("LLM не настроена (OPENROUTER_API_KEY/LLM_MODEL) — работает только /add")

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(repo=repo, llm=llm, schedule=schedule)
    dp.update.outer_middleware(AllowedUserMiddleware(settings.allowed_user_id))
    dp.include_router(setup_routers())
    summaries = Summaries(bot, repo, schedule, settings.allowed_user_id)

    try:
        await bot.set_my_commands(COMMANDS)
        me = await bot.get_me()
        log.info("Бот @%s запущен", me.username)
        summaries.start()
        await dp.start_polling(bot)
    finally:
        summaries.shutdown()
        await bot.session.close()
        await repo.close()
        await llm.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        asyncio.run(run())
    except ConfigError as e:
        log.error("%s", e)
        sys.exit(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
