"""Validated query and internal matching results; public cards come in stage 5."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re
from typing import Any, Literal
import unicodedata

from pydantic import BaseModel, ConfigDict, StrictInt, field_serializer, field_validator

from .models import CALENDAR_END, CALENDAR_START, Profile, decimal_text

RejectionCode = Literal[
    'BUSY_ON_DATE', 'UNSUPPORTED_FORMAT', 'OVER_BUDGET',
    'UNSUPPORTED_LANGUAGE', 'DURATION_EXCEEDED',
]
MatchStatus = Literal['MATCHED', 'CATEGORY_UNAVAILABLE', 'NO_MATCHES']


@dataclass(frozen=True)
class QueryIssue:
    field: str
    message: str


class QueryValidationError(ValueError):
    def __init__(self, issues: list[QueryIssue]):
        self.issues = tuple(issues)
        super().__init__('; '.join(f'{item.field}: {item.message}' for item in issues))


class RecommendationQuery(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True, revalidate_instances='always')

    city: str
    event_date: date
    event_format: str
    category: str
    budget_kzt: StrictInt
    duration_hours: Decimal | None = None
    language: str | None = None

    @field_serializer('duration_hours', when_used='json')
    def serialize_duration(self, value: Decimal | None) -> str | None:
        return decimal_text(value)

    @field_validator('city', 'event_format', 'category', 'language')
    @classmethod
    def text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            value.encode('utf-8')
        except UnicodeError as exc:
            raise ValueError('Некорректные символы Unicode') from exc
        value = ' '.join(unicodedata.normalize('NFKC', value).split())
        if not value:
            raise ValueError('Заполните обязательное поле')
        return value

    @field_validator('language', 'duration_hours', mode='before')
    @classmethod
    def empty_optional(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator('event_date', mode='before')
    @classmethod
    def calendar_date(cls, value: Any) -> date:
        if type(value) is date:
            parsed = value
        elif type(value) is str and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
            try:
                parsed = date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError('Несуществующая дата мероприятия') from exc
        else:
            raise ValueError('Дата должна иметь формат YYYY-MM-DD без времени')
        if not CALENDAR_START <= parsed <= CALENDAR_END:
            raise ValueError('Выберите дату с 23.09.2026 по 31.12.2026 включительно')
        return parsed

    @field_validator('budget_kzt')
    @classmethod
    def budget_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError('Бюджет должен быть положительным целым числом тенге')
        return value

    @field_validator('duration_hours', mode='before')
    @classmethod
    def duration_positive(cls, value: Any) -> Decimal | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if type(value) not in (int, float, Decimal):
            raise ValueError('Длительность должна быть числом, а не строкой или логическим значением')
        parsed = Decimal(str(value))
        if not parsed.is_finite() or parsed <= 0:
            raise ValueError('Длительность должна быть положительным конечным числом')
        return parsed


class MatchCounts(BaseModel):
    model_config = ConfigDict(frozen=True)
    group: int
    matched: int
    shown: int


class Exclusion(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    reasons: tuple[RejectionCode, ...]
    primary_reason: RejectionCode


class MatchResult(BaseModel):
    """Internal diagnostic result, not yet a recommendation-card API response."""
    model_config = ConfigDict(frozen=True)
    status: MatchStatus
    message: str
    query: RecommendationQuery
    catalog_version: str
    ranking_version: str
    counts: MatchCounts
    matches: tuple[Profile, ...]
    eligible_ids: tuple[str, ...]
    exclusions: tuple[Exclusion, ...]
    rejections: dict[RejectionCode, int]
