"""Утренняя и вечерняя сводки по расписанию (APScheduler 3, AsyncIOScheduler).

Вечерняя — cron в summaries.evening. Время утренней зависит от пар дня, поэтому
каждый день в 00:01 (и при старте) ставится разовая задача на сегодняшнее утро.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from bot.config import TZ, now
from bot.notion_repo import NotionError, NotionRepo
from bot.schedule import Schedule
from bot.views import build_view, date_code, status_keyboard

log = logging.getLogger(__name__)

MISFIRE_GRACE_S = 15 * 60  # если бот «проспал» время сводки, отправить в течение 15 мин


class Summaries:
    def __init__(self, bot: Bot, repo: NotionRepo, schedule: Schedule, user_id: int) -> None:
        self.bot = bot
        self.repo = repo
        self.schedule = schedule
        self.user_id = user_id
        self.scheduler = AsyncIOScheduler(timezone=TZ)

    def start(self) -> None:
        ev = self.schedule.evening
        self.scheduler.add_job(
            self.send_evening,
            CronTrigger(hour=ev.hour, minute=ev.minute, timezone=TZ),
            id="evening",
            misfire_grace_time=MISFIRE_GRACE_S,
            coalesce=True,
        )
        self.scheduler.add_job(
            self.plan_morning,
            CronTrigger(hour=0, minute=1, timezone=TZ),
            id="plan_morning",
            misfire_grace_time=MISFIRE_GRACE_S,
            coalesce=True,
        )
        self.scheduler.start()
        self.plan_morning()
        for job in self.scheduler.get_jobs():
            log.info("Задача %s: следующий запуск %s", job.id, job.next_run_time)

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def morning_at(self, d: date) -> datetime:
        return datetime.combine(d, self.schedule.morning_time(d), tzinfo=TZ)

    def plan_morning(self) -> None:
        d = now().date()
        run_at = self.morning_at(d)
        if run_at <= now():
            log.info("Утренняя сводка на %s (%s) уже прошла — пропускаю", d, run_at.strftime("%H:%M"))
            return
        self.scheduler.add_job(
            self.send_morning,
            DateTrigger(run_date=run_at, timezone=TZ),
            args=[d],
            id="morning",
            replace_existing=True,
            misfire_grace_time=MISFIRE_GRACE_S,
        )
        log.info("Утренняя сводка на %s запланирована на %s", d, run_at.strftime("%H:%M"))

    async def send_morning(self, d: date | None = None) -> None:
        await self._send(date_code("M", d or now().date()), "утренняя")

    async def send_evening(self) -> None:
        await self._send(date_code("E", now().date() + timedelta(days=1)), "вечерняя")

    async def _send(self, code: str, name: str) -> None:
        try:
            tasks = await self.repo.open_tasks()
            view = build_view(code, tasks, self.repo, self.schedule)
            await self.bot.send_message(
                self.user_id,
                view.render(),
                reply_markup=status_keyboard(view.tasks, code),
                disable_web_page_preview=True,
            )
            log.info("Отправлена %s сводка (%s)", name, code)
        except NotionError as e:
            log.error("Сводка %s: ошибка Notion: %s", name, e)
            await self._notify(f"⚠️ Не удалось собрать {name} сводку: {e}")
        except Exception:
            log.exception("Сводка %s: непредвиденная ошибка", name)
            await self._notify(f"⚠️ Не удалось отправить {name} сводку. Подробности в логе.")

    async def _notify(self, text: str) -> None:
        try:
            await self.bot.send_message(self.user_id, text)
        except Exception:
            log.exception("Не удалось отправить уведомление об ошибке")
