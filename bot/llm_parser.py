"""Разбор свободного текста в задачу через LLM (OpenRouter, OpenAI-совместимый API)."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, ValidationError, field_validator

from bot.config import TZ
from bot.models import CATEGORIES, SECTIONS, NewTask

log = logging.getLogger(__name__)

WEEKDAYS_FULL = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


class LLMError(RuntimeError):
    """LLM недоступна или вернула мусор. Текст — для пользователя."""


class LLMTask(BaseModel):
    """Строгая схема ответа LLM."""

    title: str
    due: str | None = None
    due_is_datetime: bool = False
    category: str | None = None
    section: str | None = None
    notes: str | None = None

    @field_validator("title")
    @classmethod
    def _title_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("пустой title")
        return v


def build_prompt(
    text: str,
    now: datetime,
    categories: tuple[str, ...] = CATEGORIES,
    sections: tuple[str, ...] = SECTIONS,
) -> list[dict[str, str]]:
    today = now.date()
    system = (
        "Ты разбираешь сообщение студента в задачу для трекера. "
        "Отвечай ТОЛЬКО JSON-объектом без пояснений и без markdown.\n\n"
        f"Сегодня: {today.isoformat()} ({WEEKDAYS_FULL[today.weekday()]}), "
        f"сейчас {now:%H:%M}, часовой пояс Europe/Moscow.\n"
        "Относительные даты («завтра», «послезавтра», «к пятнице», «через неделю») "
        "считай от сегодняшней даты. «К пятнице» = ближайшая пятница после сегодня.\n\n"
        "Поля JSON:\n"
        '- "title": строка, короткое название задачи (обязательно)\n'
        '- "due": срок; "YYYY-MM-DD" если время не указано, "YYYY-MM-DDTHH:MM" если указано; null если срока нет\n'
        '- "due_is_datetime": true, только если в сообщении указано время\n'
        f'- "category": ровно одно значение из списка или null: {json.dumps(categories, ensure_ascii=False)}\n'
        f'- "section": ровно одно значение из списка или null: {json.dumps(sections, ensure_ascii=False)}\n'
        '- "notes": доп. детали из сообщения, которых нет в title, или null\n\n'
        "Значения category и section копируй из списков символ в символ, вместе с эмодзи.\n"
        "Не выдумывай срок, категорию или раздел, если их нельзя понять из текста — ставь null."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": text}]


def _extract_json(raw: str) -> str:
    """Некоторые модели оборачивают JSON в ```json ... ``` — снимаем обёртку."""
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if m:
        return m.group(1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    return raw[start : end + 1] if start != -1 and end > start else raw


def _normalize(value: str) -> str:
    """Только буквы/цифры в нижнем регистре, ё→е: «🔥 Горит сейчас» ≈ «горит сейчас.»"""
    return "".join(ch for ch in value.lower().replace("ё", "е") if ch.isalnum())


def _match_option(value: str | None, options: tuple[str, ...]) -> str | None:
    """Точное значение select из списка, если LLM вернула его без эмодзи/с опечаткой в регистре."""
    if not value or not value.strip():
        return None
    if value in options:
        return value
    key = _normalize(value)
    for opt in options:
        if key and _normalize(opt) == key:
            return opt
    return None


def validate_llm_json(
    raw: str,
    categories: tuple[str, ...] = CATEGORIES,
    sections: tuple[str, ...] = SECTIONS,
) -> tuple[NewTask, list[str]]:
    """Проверяет ответ LLM. Возвращает задачу и список предупреждений.

    Битый JSON или нет title → LLMError.
    Недопустимые категория/раздел/дата → поле пустое + предупреждение.
    """
    try:
        data = json.loads(_extract_json(raw))
        if not isinstance(data, dict):
            raise ValueError("ожидался JSON-объект")
        parsed = LLMTask.model_validate(data)
    except (ValueError, ValidationError) as e:
        log.warning("Невалидный ответ LLM: %s | raw=%r", e, raw[:500])
        raise LLMError("LLM вернула некорректный ответ.") from e

    warnings: list[str] = []

    category = _match_option(parsed.category, categories)
    if parsed.category and category is None:
        warnings.append(f"категория «{parsed.category}» не распознана")
    section = _match_option(parsed.section, sections)
    if parsed.section and section is None:
        warnings.append(f"раздел «{parsed.section}» не распознан")

    due_date: date | None = None
    due_dt: datetime | None = None
    if parsed.due:
        try:
            if parsed.due_is_datetime and "T" in parsed.due:
                due_dt = datetime.fromisoformat(parsed.due)
                due_dt = due_dt.replace(tzinfo=TZ) if due_dt.tzinfo is None else due_dt.astimezone(TZ)
                due_date = due_dt.date()
            else:
                due_date = date.fromisoformat(parsed.due[:10])
        except ValueError:
            warnings.append(f"срок «{parsed.due}» не распознан")
            due_date, due_dt = None, None

    task = NewTask(
        title=parsed.title,
        due_date=due_date,
        due_datetime=due_dt,
        category=category,
        section=section,
        notes=(parsed.notes or "").strip(),
    )
    return task, warnings


class LLMParser:
    def __init__(self, api_key: str | None, base_url: str, model: str | None) -> None:
        self.enabled = bool(api_key and model)
        self._model = model
        self._client = (
            AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=60.0, max_retries=1)
            if self.enabled
            else None
        )

    async def parse(
        self,
        text: str,
        now: datetime,
        categories: tuple[str, ...] = CATEGORIES,
        sections: tuple[str, ...] = SECTIONS,
    ) -> tuple[NewTask, list[str]]:
        if not self.enabled or self._client is None:
            raise LLMError("LLM не настроена (нет OPENROUTER_API_KEY или LLM_MODEL).")
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=build_prompt(text, now, categories, sections),
                response_format={"type": "json_object"},
                temperature=0,
            )
        except OpenAIError as e:
            log.error("Ошибка LLM: %s: %s", type(e).__name__, e)
            raise LLMError("LLM недоступна.") from e
        if not resp.choices or not resp.choices[0].message.content:
            log.warning("Пустой ответ LLM: %r", resp)
            raise LLMError("LLM вернула пустой ответ.")
        return validate_llm_json(resp.choices[0].message.content, categories, sections)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
