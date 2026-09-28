import asyncio
import json
from datetime import date, datetime
from types import SimpleNamespace

import httpx
import pytest
from openai import NotFoundError, RateLimitError

from bot.config import TZ
from bot.llm_parser import LLMError, LLMParser, build_prompt, validate_llm_json


def _raw(**fields) -> str:
    return json.dumps(fields, ensure_ascii=False)


def test_valid_json() -> None:
    task, warnings = validate_llm_json(
        _raw(
            title="ДЗ по ТОЭ",
            due="2026-09-25",
            due_is_datetime=False,
            category="ТОЭ",
            section="🔥 Горит сейчас",
            notes="задачи 1.2.1–1.2.5",
        )
    )
    assert warnings == []
    assert task.title == "ДЗ по ТОЭ"
    assert task.due_date == date(2026, 9, 25)
    assert task.due_datetime is None
    assert task.category == "ТОЭ"
    assert task.section == "🔥 Горит сейчас"
    assert task.notes == "задачи 1.2.1–1.2.5"


def test_valid_json_with_time() -> None:
    task, _ = validate_llm_json(
        _raw(title="Созвон", due="2026-09-21T15:30", due_is_datetime=True, category=None, section=None, notes=None)
    )
    assert task.due_datetime == datetime(2026, 9, 21, 15, 30, tzinfo=TZ)
    assert task.due_date == date(2026, 9, 21)
    assert task.notes == ""


def test_invalid_category_and_section() -> None:
    task, warnings = validate_llm_json(
        _raw(title="Лаба", due="2026-09-22", due_is_datetime=False, category="Химия", section="Срочно", notes=None)
    )
    assert task.title == "Лаба"
    assert task.category is None
    assert task.section is None
    assert any("Химия" in w for w in warnings)
    assert any("Срочно" in w for w in warnings)


def test_select_matched_without_emoji_and_punctuation() -> None:
    task, warnings = validate_llm_json(
        _raw(title="x", category="учеба (прочее)", section="Горит сейчас.")
    )
    assert task.category == "Учёба (прочее)"
    assert task.section == "🔥 Горит сейчас"
    assert warnings == []


def test_options_come_from_argument() -> None:
    task, warnings = validate_llm_json(_raw(title="x", section="Быт"), sections=("🏠 Быт",))
    assert task.section == "🏠 Быт" and warnings == []


@pytest.mark.parametrize(
    "raw",
    [
        '{"title": "Лаба", "due": ',     # оборванный JSON
        "Конечно! Вот задача: Лаба",      # вообще не JSON
        '["title", "Лаба"]',               # не объект
        '{"due": "2026-09-22"}',           # нет title
        '{"title": "   "}',                # пустой title
    ],
)
def test_broken_json(raw: str) -> None:
    with pytest.raises(LLMError):
        validate_llm_json(raw)


def test_json_in_code_fence() -> None:
    task, _ = validate_llm_json('```json\n{"title": "Лаба"}\n```')
    assert task.title == "Лаба"


def test_bad_due_is_dropped_with_warning() -> None:
    task, warnings = validate_llm_json(_raw(title="x", due="к пятнице", due_is_datetime=False))
    assert task.due_date is None
    assert any("срок" in w for w in warnings)


def test_prompt_contains_date_weekday_and_options() -> None:
    msgs = build_prompt("сдать дз к пятнице", datetime(2026, 9, 19, 12, 0, tzinfo=TZ))
    system = msgs[0]["content"]
    assert "2026-09-19" in system and "суббота" in system
    assert "Инженерная графика" in system and "🔥 Горит сейчас" in system
    assert msgs[1] == {"role": "user", "content": "сдать дз к пятнице"}


# ---------- запасные модели ----------

class _FakeCompletions:
    """Отвечает по сценарию: исключение или текст ответа на каждый вызов."""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.used: list[str] = []

    async def create(self, model: str, **kwargs):
        self.used.append(model)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        msg = SimpleNamespace(content=item)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _parser(script: list, models: str) -> LLMParser:
    p = LLMParser("fake-key", "http://localhost", models)
    p._client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions(script)))
    return p


def _err(cls, status: int):
    resp = httpx.Response(status, request=httpx.Request("POST", "http://localhost"))
    return cls("boom", response=resp, body=None)


def test_models_parsed_from_comma_list() -> None:
    p = LLMParser("k", "http://localhost", " a/one:free , b/two ")
    assert p.models == ["a/one:free", "b/two"] and p.enabled


def test_falls_back_to_next_model_on_404() -> None:
    p = _parser([_err(NotFoundError, 404), _raw(title="Лаба")], "gone/model:free,good/model:free")
    task, _ = asyncio.run(p.parse("лаба", datetime(2026, 9, 29, 12, 0, tzinfo=TZ)))
    assert task.title == "Лаба"
    assert p._client.chat.completions.used == ["gone/model:free", "good/model:free"]


def test_falls_back_on_rate_limit() -> None:
    p = _parser([_err(RateLimitError, 429), _raw(title="Лаба")], "busy/model:free,good/model:free")
    task, _ = asyncio.run(p.parse("лаба", datetime(2026, 9, 29, 12, 0, tzinfo=TZ)))
    assert task.title == "Лаба"


def test_all_models_unavailable() -> None:
    p = _parser([_err(NotFoundError, 404), _err(RateLimitError, 429)], "a:free,b:free")
    with pytest.raises(LLMError, match="LLM_MODEL"):
        asyncio.run(p.parse("лаба", datetime(2026, 9, 29, 12, 0, tzinfo=TZ)))


def test_no_models_configured() -> None:
    p = LLMParser("k", "http://localhost", "")
    assert not p.enabled
    with pytest.raises(LLMError):
        asyncio.run(p.parse("лаба", datetime(2026, 9, 29, 12, 0, tzinfo=TZ)))
