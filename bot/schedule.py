"""Расписание пар: чтение schedule.yaml, чётность недель, время сводок."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import yaml

WEEKDAY_KEYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
WEEK_A, WEEK_B = "А", "Б"
# Латинские A/B тоже принимаем — их легко перепутать с кириллицей.
_WEEK_ALIASES = {"А": WEEK_A, "A": WEEK_A, "Б": WEEK_B, "B": WEEK_B}


class ScheduleError(ValueError):
    pass


@dataclass(frozen=True)
class Lesson:
    slot: int
    start: time
    end: time
    name: str
    kind: str = ""
    online: bool = False


@dataclass(frozen=True)
class _Entry:
    slot: int
    variants: dict[str, dict[str, Any]]  # {"*": {...}} или {"А": {...}, "Б": {...}}


def _parse_time(value: Any, where: str) -> time:
    try:
        return time.fromisoformat(str(value).strip())
    except ValueError:
        raise ScheduleError(f"{where}: время «{value}» не в формате ЧЧ:ММ") from None


class Schedule:
    def __init__(self, data: dict[str, Any], week_a_monday: date) -> None:
        if week_a_monday.weekday() != 0:
            raise ScheduleError("WEEK_A_MONDAY должен быть понедельником")
        self.week_a_monday = week_a_monday

        try:
            self.slots: dict[int, tuple[time, time]] = {
                int(k): (_parse_time(v[0], f"slots.{k}"), _parse_time(v[1], f"slots.{k}"))
                for k, v in (data.get("slots") or {}).items()
            }
        except (TypeError, IndexError, ValueError) as e:
            raise ScheduleError(f"slots: неверный формат ({e})") from None
        if not self.slots:
            raise ScheduleError("slots: не задано время пар")

        s = data.get("summaries") or {}
        self.morning_before_first = timedelta(minutes=int(s.get("morning_before_first_min", 120)))
        self.morning_before_online = timedelta(minutes=int(s.get("morning_before_online_min", 30)))
        self.morning_no_lessons = _parse_time(s.get("morning_no_lessons", "10:00"), "summaries.morning_no_lessons")
        self.evening = _parse_time(s.get("evening", "22:30"), "summaries.evening")

        week = data.get("week") or {}
        unknown = set(week) - set(WEEKDAY_KEYS)
        if unknown:
            raise ScheduleError(f"week: неизвестные дни {sorted(unknown)}")
        self._days: dict[int, list[_Entry]] = {
            i: [self._parse_entry(e, key) for e in (week.get(key) or [])]
            for i, key in enumerate(WEEKDAY_KEYS)
        }

    def _parse_entry(self, raw: Any, day: str) -> _Entry:
        where = f"week.{day}"
        if not isinstance(raw, dict) or "slot" not in raw:
            raise ScheduleError(f"{where}: у пары нет поля slot")
        slot = int(raw["slot"])
        if slot not in self.slots:
            raise ScheduleError(f"{where}: пара №{slot} — нет такого слота в slots")
        variants: dict[str, dict[str, Any]] = {}
        for key, value in raw.items():
            if str(key) in _WEEK_ALIASES:
                if not isinstance(value, dict) or not value.get("name"):
                    raise ScheduleError(f"{where}, пара №{slot}: у недели {key} нет name")
                variants[_WEEK_ALIASES[str(key)]] = value
        if not variants:
            if not raw.get("name"):
                raise ScheduleError(f"{where}, пара №{slot}: нет name")
            variants["*"] = raw
        return _Entry(slot=slot, variants=variants)

    # ---------- загрузка ----------

    @classmethod
    def load(cls, path: Path, week_a_monday: date) -> "Schedule":
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            raise ScheduleError(
                f"Не найден файл расписания {path.name} — скопируй schedule.example.yaml "
                f"в {path.name} и впиши свои пары"
            ) from None
        except yaml.YAMLError as e:
            raise ScheduleError(f"{path.name}: ошибка YAML — {e}") from None
        if not isinstance(data, dict):
            raise ScheduleError(f"{path.name}: ожидался словарь верхнего уровня")
        return cls(data, week_a_monday)

    # ---------- расчёты ----------

    def week_letter(self, d: date) -> str:
        """«А» или «Б»: неделя, содержащая WEEK_A_MONDAY, — А, дальше чередуются."""
        monday = d - timedelta(days=d.weekday())
        weeks = (monday - self.week_a_monday).days // 7
        return WEEK_A if weeks % 2 == 0 else WEEK_B

    def lessons_for(self, d: date) -> list[Lesson]:
        letter = self.week_letter(d)
        result = []
        for e in self._days[d.weekday()]:
            v = e.variants.get("*") or e.variants.get(letter)
            if v is None:
                continue  # пара только по другой неделе
            start, end = self.slots[e.slot]
            result.append(
                Lesson(
                    slot=e.slot,
                    start=start,
                    end=end,
                    name=str(v["name"]),
                    kind=str(v.get("kind") or ""),
                    online=bool(v.get("online", False)),
                )
            )
        return sorted(result, key=lambda l: l.slot)

    def morning_time(self, d: date) -> time:
        lessons = self.lessons_for(d)
        if not lessons:
            return self.morning_no_lessons
        first = lessons[0]
        offset = self.morning_before_online if first.online else self.morning_before_first
        return (datetime.combine(d, first.start) - offset).time()
