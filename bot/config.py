"""Чтение настроек из .env."""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pydantic import BaseModel, SecretStr, ValidationError, field_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("Europe/Moscow")

def now() -> datetime:
    """Текущее время в Europe/Moscow."""
    return datetime.now(TZ)


class ConfigError(RuntimeError):
    """Ошибка конфигурации. Текст никогда не содержит значений секретов."""


class Settings(BaseModel):
    bot_token: SecretStr
    allowed_user_id: int

    notion_token: SecretStr
    notion_data_source_id: str

    openrouter_api_key: SecretStr | None = None
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str | None = None

    week_a_monday: date = date(2026, 8, 31)
    schedule_path: Path = PROJECT_ROOT / "schedule.yaml"
    log_level: str = "INFO"

    @field_validator("week_a_monday")
    @classmethod
    def _must_be_monday(cls, v: date) -> date:
        if v.weekday() != 0:
            raise ValueError("WEEK_A_MONDAY должен быть понедельником")
        return v


_ENV_KEYS = {
    "bot_token": "BOT_TOKEN",
    "allowed_user_id": "ALLOWED_USER_ID",
    "notion_token": "NOTION_TOKEN",
    "notion_data_source_id": "NOTION_DATA_SOURCE_ID",
    "openrouter_api_key": "OPENROUTER_API_KEY",
    "llm_base_url": "LLM_BASE_URL",
    "llm_model": "LLM_MODEL",
    "week_a_monday": "WEEK_A_MONDAY",
    "log_level": "LOG_LEVEL",
}


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or PROJECT_ROOT / ".env")
    raw = {}
    for field, key in _ENV_KEYS.items():
        value = os.getenv(key, "").strip()
        if value:  # пустые значения = «не задано», берётся дефолт
            raw[field] = value
    try:
        return Settings(**raw)
    except ValidationError as e:
        # Сообщаем только имена переменных и причину, без значений.
        problems = []
        for err in e.errors():
            field = str(err["loc"][0]) if err["loc"] else "?"
            problems.append(f"{_ENV_KEYS.get(field, field)}: {err['msg']}")
        raise ConfigError("Ошибка в .env — " + "; ".join(problems)) from None
