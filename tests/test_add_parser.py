from datetime import date, datetime

import pytest

from bot.add_parser import AddParseError, parse_add
from bot.config import TZ

TODAY = date(2026, 9, 19)


def test_title_only() -> None:
    t = parse_add("Купить тетради", TODAY)
    assert t.title == "Купить тетради" and t.due_date is None


def test_title_and_date() -> None:
    t = parse_add("Лаба по физике | 25.09", TODAY)
    assert t.title == "Лаба по физике" and t.due_date == date(2026, 9, 25) and t.due_datetime is None


def test_date_with_year_and_time() -> None:
    t = parse_add("Курсач | 25.09.2026 18:00", TODAY)
    assert t.due_datetime == datetime(2026, 9, 25, 18, 0, tzinfo=TZ)


def test_short_year() -> None:
    assert parse_add("x | 01.02.27", TODAY).due_date == date(2027, 2, 1)


def test_recent_past_date_stays_this_year() -> None:
    assert parse_add("x | 18.09", TODAY).due_date == date(2026, 9, 18)


def test_far_past_date_moves_to_next_year() -> None:
    assert parse_add("x | 01.08", TODAY).due_date == date(2027, 8, 1)


@pytest.mark.parametrize("text", ["", " | 25.09", "x | 31.02", "x | завтра", "x | 25.09 25:00"])
def test_errors(text: str) -> None:
    with pytest.raises(AddParseError):
        parse_add(text, TODAY)
