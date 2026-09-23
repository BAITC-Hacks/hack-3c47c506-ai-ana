"""Strict catalog schema; original display strings and descriptions are preserved."""
from datetime import date
from decimal import Decimal
import re
import unicodedata
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, field_serializer, field_validator

CALENDAR_START = date(2026, 9, 23)
CALENDAR_END = date(2026, 12, 31)
CITIES = ('Алматы', 'Астана', 'Зарубежье')
FORMATS = ('свадьба', 'той', 'корпоратив', 'конференция', 'юбилей', 'день рождения')
LANGUAGES = ('русский', 'казахский', 'английский')


def normalize_key(value: str) -> str:
    """Exact comparison key, with no fuzzy matching or inferred aliases."""
    return ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()


def decimal_text(value: Decimal | None) -> str | None:
    """Context-independent, compact canonical text for diagnostic JSON decimals."""
    if value is None:
        return None
    sign, digits_tuple, exponent = value.as_tuple()
    digits = list(digits_tuple)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    coefficient = ('-' if sign else '') + ''.join(map(str, digits))
    return coefficient + (f'e{exponent}' if exponent else '')


class Profile(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)

    id: str
    anon_name: str
    categories: tuple[str, ...]
    city: str
    price_from_kzt: StrictInt
    event_formats: tuple[str, ...]
    languages: tuple[str, ...]
    max_hours: Decimal | None  # Required field; null has its own meaning.
    busy_dates: tuple[date, ...]
    description: str
    synthetic: StrictBool
    city_imputed: StrictBool
    price_imputed: StrictBool

    @field_serializer('max_hours', when_used='json')
    def serialize_duration(self, value: Decimal | None) -> str | None:
        return decimal_text(value)

    @field_validator('id', 'anon_name', 'city', 'description')
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not normalize_key(value):
            raise ValueError('Строка не должна быть пустой')
        return value

    @field_validator('city')
    @classmethod
    def city_allowed(cls, value: str) -> str:
        if normalize_key(value) not in {normalize_key(v) for v in CITIES}:
            raise ValueError('Неизвестный город')
        return value

    @field_validator('price_from_kzt')
    @classmethod
    def price_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError('Цена должна быть положительным целым числом тенге')
        return value

    @field_validator('categories', 'event_formats', 'languages', mode='before')
    @classmethod
    def string_list(cls, value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)) or not value:
            raise ValueError('Ожидается непустой список строк')
        if any(type(item) is not str or not normalize_key(item) for item in value):
            raise ValueError('Элементы списка должны быть непустыми строками')
        if len({normalize_key(item) for item in value}) != len(value):
            raise ValueError('Список содержит повторяющиеся значения')
        return tuple(value)

    @field_validator('event_formats', 'languages')
    @classmethod
    def known_values(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        allowed = FORMATS if info.field_name == 'event_formats' else LANGUAGES
        if any(normalize_key(item) not in {normalize_key(v) for v in allowed} for item in value):
            raise ValueError('Неизвестное значение справочника')
        return value

    @field_validator('max_hours', mode='before')
    @classmethod
    def duration(cls, value: Any) -> Decimal | None:
        if value is None:
            return None
        if type(value) not in (int, float, Decimal):
            raise ValueError('Длительность должна быть числом или null')
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            raise ValueError('Длительность должна быть положительным конечным числом')
        return number

    @field_validator('busy_dates', mode='before')
    @classmethod
    def calendar(cls, value: Any) -> tuple[date, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError('Календарь должен быть списком дат, даже если он пуст')
        dates = []
        for item in value:
            if type(item) is date:
                parsed = item
            elif type(item) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}', item):
                try:
                    parsed = date.fromisoformat(item)
                except ValueError as exc:
                    raise ValueError('Несуществующая календарная дата') from exc
            else:
                raise ValueError('Дата должна иметь формат YYYY-MM-DD')
            if not CALENDAR_START <= parsed <= CALENDAR_END:
                raise ValueError('Дата вне окна 23.09.2026–31.12.2026')
            dates.append(parsed)
        if len(set(dates)) != len(dates):
            raise ValueError('Календарь содержит повторяющиеся даты')
        return tuple(dates)
