from datetime import date, time
from pathlib import Path

import pytest

from bot.config import PROJECT_ROOT
from bot.schedule import Schedule, ScheduleError

WEEK_A_MONDAY = date(2026, 8, 31)

# Тестовое расписание — отдельно от schedule.yaml, который правится вручную.
# Первая пара: Пн/Вт — 1-я, Ср — 1-я онлайн, Чт — 2-я, Пт — 3-я, Сб/Вс — нет.
TEST_SCHEDULE = """
slots:
  1: ["08:00", "09:35"]
  2: ["09:50", "11:25"]
  3: ["11:40", "13:15"]
  4: ["13:40", "15:15"]
  5: ["15:30", "17:05"]
week:
  monday:
    - {slot: 1, name: Математика, kind: лек}
    - {slot: 2, name: Математика, kind: пр}
  tuesday:
    - {slot: 1, name: История, kind: лек}
    - {slot: 2, name: Экономика, kind: пр}
    - slot: 3
      А: {name: Химия, kind: лаб}
      Б: {name: Физика, kind: пр}
  wednesday:
    - {slot: 1, name: Информатика, kind: пр, online: true}
  thursday:
    - {slot: 2, name: Черчение, kind: пр}
    - slot: 3
      А: {name: Физика, kind: лаб}
      Б: {name: Математика, kind: пр}
    - {slot: 4, name: Физика, kind: лек}
    - {slot: 5, name: Электротехника, kind: пр}
  friday:
    - {slot: 3, name: Английский язык}
    - {slot: 4, name: Электротехника, kind: лек}
"""


@pytest.fixture(scope="module")
def schedule(tmp_path_factory: pytest.TempPathFactory) -> Schedule:
    p = tmp_path_factory.mktemp("sch") / "schedule.yaml"
    p.write_text(TEST_SCHEDULE, encoding="utf-8")
    return Schedule.load(p, WEEK_A_MONDAY)


def test_example_schedule_file_is_valid() -> None:
    """schedule.example.yaml из репозитория загружается без ошибок и в нём есть пары."""
    real = Schedule.load(PROJECT_ROOT / "schedule.example.yaml", WEEK_A_MONDAY)
    week = [date(2026, 9, 14 + i) for i in range(7)]
    assert any(real.lessons_for(d) for d in week)
    for d in week:
        real.morning_time(d)


# ---------- чётность недели ----------

@pytest.mark.parametrize(
    "d, letter",
    [
        (date(2026, 8, 31), "А"),  # сам WEEK_A_MONDAY
        (date(2026, 9, 6), "А"),   # воскресенье той же недели
        (date(2026, 9, 7), "Б"),
        (date(2026, 9, 13), "Б"),
        (date(2026, 9, 14), "А"),
        (date(2026, 9, 24), "Б"),
        (date(2026, 8, 30), "Б"),  # неделя до точки отсчёта
        (date(2026, 8, 24), "Б"),
        (date(2026, 8, 17), "А"),
    ],
)
def test_week_letter(schedule: Schedule, d: date, letter: str) -> None:
    assert schedule.week_letter(d) == letter


def test_week_a_monday_must_be_monday() -> None:
    with pytest.raises(ScheduleError):
        Schedule({"slots": {1: ["08:00", "09:35"]}}, date(2026, 9, 1))


# ---------- время утренней сводки ----------

@pytest.mark.parametrize(
    "d, expected",
    [
        (date(2026, 9, 14), time(6, 0)),   # Пн — 1-я пара 08:00
        (date(2026, 9, 15), time(6, 0)),   # Вт — 1-я пара 08:00
        (date(2026, 9, 16), time(7, 30)),  # Ср — 1-я пара онлайн → за 30 мин
        (date(2026, 9, 17), time(7, 50)),  # Чт — 1-я пара 2-я (09:50)
        (date(2026, 9, 18), time(9, 40)),  # Пт — 1-я пара 3-я (11:40)
        (date(2026, 9, 19), time(10, 0)),  # Сб
        (date(2026, 9, 20), time(10, 0)),  # Вс
        # те же дни недели Б — время не меняется
        (date(2026, 9, 21), time(6, 0)),
        (date(2026, 9, 22), time(6, 0)),
        (date(2026, 9, 23), time(7, 30)),
        (date(2026, 9, 24), time(7, 50)),
        (date(2026, 9, 25), time(9, 40)),
        (date(2026, 9, 26), time(10, 0)),
        (date(2026, 9, 27), time(10, 0)),
    ],
)
def test_morning_time(schedule: Schedule, d: date, expected: time) -> None:
    assert schedule.morning_time(d) == expected


def test_morning_time_weekday_without_lessons() -> None:
    s = Schedule({"slots": {1: ["08:00", "09:35"]}, "week": {}}, WEEK_A_MONDAY)
    assert s.morning_time(date(2026, 9, 14)) == time(10, 0)


# ---------- пары по неделям А/Б ----------

def _names(schedule: Schedule, d: date) -> list[tuple[int, str, str]]:
    return [(l.slot, l.name, l.kind) for l in schedule.lessons_for(d)]


def test_tuesday_week_a(schedule: Schedule) -> None:
    assert _names(schedule, date(2026, 9, 15)) == [
        (1, "История", "лек"),
        (2, "Экономика", "пр"),
        (3, "Химия", "лаб"),
    ]


def test_tuesday_week_b(schedule: Schedule) -> None:
    assert _names(schedule, date(2026, 9, 22))[2] == (3, "Физика", "пр")


def test_thursday_week_a_and_b(schedule: Schedule) -> None:
    a = _names(schedule, date(2026, 9, 17))
    b = _names(schedule, date(2026, 9, 24))
    assert a[1] == (3, "Физика", "лаб")
    assert b[1] == (3, "Математика", "пр")
    # остальные пары одинаковые
    assert [x for x in a if x[0] != 3] == [x for x in b if x[0] != 3] == [
        (2, "Черчение", "пр"),
        (4, "Физика", "лек"),
        (5, "Электротехника", "пр"),
    ]


def test_wednesday_online(schedule: Schedule) -> None:
    (lesson,) = schedule.lessons_for(date(2026, 9, 16))
    assert lesson.name == "Информатика" and lesson.online


def test_weekend_no_lessons(schedule: Schedule) -> None:
    assert schedule.lessons_for(date(2026, 9, 19)) == []
    assert schedule.lessons_for(date(2026, 9, 20)) == []


def test_lesson_only_one_week() -> None:
    s = Schedule(
        {
            "slots": {1: ["08:00", "09:35"], 2: ["09:50", "11:25"]},
            "week": {"monday": [{"slot": 1, "A": {"name": "Только А"}}, {"slot": 2, "name": "Всегда"}]},
        },
        WEEK_A_MONDAY,
    )
    assert [l.name for l in s.lessons_for(date(2026, 8, 31))] == ["Только А", "Всегда"]
    assert [l.name for l in s.lessons_for(date(2026, 9, 7))] == ["Всегда"]
    # на неделе Б первая пара — 2-я, значит утренняя сводка позже
    assert s.morning_time(date(2026, 9, 7)) == time(7, 50)


# ---------- ошибки в файле ----------

@pytest.mark.parametrize(
    "text",
    [
        "slots: {1: ['08:00', '09:35']}\nweek: {monday: [{slot: 7, name: X}]}",  # нет такого слота
        "slots: {1: ['08:00', '09:35']}\nweek: {monday: [{slot: 1}]}",           # нет name
        "slots: {1: ['8 утра', '09:35']}",                                       # плохое время
        "slots: {1: ['08:00', '09:35']}\nweek: {funday: []}",                    # нет такого дня
        "slots: [",                                                              # битый YAML
    ],
)
def test_bad_schedule_file(tmp_path: Path, text: str) -> None:
    p = tmp_path / "schedule.yaml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ScheduleError):
        Schedule.load(p, WEEK_A_MONDAY)
