"""Pure matching: validate, filter all candidates, sort and take up to three."""
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from .catalog import Catalog
from .matching_models import (
    Exclusion, MatchCounts, MatchResult, QueryIssue, QueryValidationError,
    RecommendationQuery, RejectionCode,
)
from .models import Profile, normalize_key

RANKING_VERSION = 'price-asc-canonical-id-v1'
REJECTION_ORDER: tuple[RejectionCode, ...] = (
    'BUSY_ON_DATE', 'UNSUPPORTED_FORMAT', 'OVER_BUDGET',
    'UNSUPPORTED_LANGUAGE', 'DURATION_EXCEEDED',
)
REJECTION_LABELS = {
    'BUSY_ON_DATE': 'занятость на дату',
    'UNSUPPORTED_FORMAT': 'неподдерживаемый формат',
    'OVER_BUDGET': 'начальная цена выше бюджета',
    'UNSUPPORTED_LANGUAGE': 'неподдерживаемый язык',
    'DURATION_EXCEEDED': 'длительность выше лимита',
}


def _validate_query(query: RecommendationQuery | Mapping[str, Any], catalog: Catalog) -> RecommendationQuery:
    try:
        validated = RecommendationQuery.model_validate(query)
    except ValidationError as exc:
        messages = {
            'missing': 'Заполните обязательное поле',
            'extra_forbidden': 'Неизвестное поле запроса',
            'int_type': 'Бюджет должен быть целым числом тенге, а не строкой или логическим значением',
            'string_type': 'Ожидается строка',
            'model_type': 'Запрос должен быть объектом с параметрами мероприятия',
        }
        raise QueryValidationError([
            QueryIssue('.'.join(map(str, err['loc'])) or 'query',
                       messages.get(err['type'], err['msg'].removeprefix('Value error, ')))
            for err in exc.errors(include_input=False, include_url=False)
        ]) from exc

    # Dictionaries are taken across the whole catalog, not just the city/category group.
    # Thus a known category in another city still produces CATEGORY_UNAVAILABLE.
    updates: dict[str, str] = {}
    issues = []
    fields = {'city': 'city', 'category': 'categories', 'event_format': 'event_formats', 'language': 'languages'}
    for request_field, profile_field in fields.items():
        requested = getattr(validated, request_field)
        if requested is None:
            continue
        labels: dict[str, str] = {}
        for profile in catalog.profiles:
            values = (profile.city,) if profile_field == 'city' else getattr(profile, profile_field)
            for label in values:
                key = normalize_key(label)
                # Sorting-independent display spelling, while original profiles are untouched.
                labels[key] = min(labels.get(key, label), label)
        key = normalize_key(requested)
        if key not in labels:
            issues.append(QueryIssue(request_field, 'Значение отсутствует в справочнике каталога'))
        else:
            updates[request_field] = labels[key]
    if issues:
        raise QueryValidationError(issues)
    return RecommendationQuery.model_validate(validated.model_copy(update=updates))


def _reasons(profile: Profile, query: RecommendationQuery) -> tuple[RejectionCode, ...]:
    violations: list[RejectionCode] = []
    if query.event_date in profile.busy_dates:
        violations.append('BUSY_ON_DATE')
    if normalize_key(query.event_format) not in {normalize_key(value) for value in profile.event_formats}:
        violations.append('UNSUPPORTED_FORMAT')
    if profile.price_from_kzt > query.budget_kzt:
        violations.append('OVER_BUDGET')
    if query.language is not None and normalize_key(query.language) not in {normalize_key(value) for value in profile.languages}:
        violations.append('UNSUPPORTED_LANGUAGE')
    if query.duration_hours is not None and profile.max_hours is not None and query.duration_hours > profile.max_hours:
        violations.append('DURATION_EXCEEDED')
    return tuple(violations)


def _message(query: RecommendationQuery, counts: MatchCounts, rejections: dict[RejectionCode, int]) -> str:
    if not counts.group:
        return f'В нашем каталоге нет категории «{query.category}» в городе «{query.city}».'
    context = f'Профилей в категории города: {counts.group}. Подходят по условиям: {counts.matched}.'
    if counts.matched:
        headline = f'Показаны {counts.shown} из {counts.matched} подходящих.'
        if counts.matched < 3:
            if counts.group == counts.matched:
                headline += f' В группе всего {counts.group}; все проходят условия.'
            else:
                headline += ' Остальные профили не проходят обязательные условия.'
    else:
        headline = 'Кандидаты есть, но по заданным условиям нет подходящих.'
    diagnostic = ', '.join(f'{REJECTION_LABELS[code]} — {rejections[code]}' for code in REJECTION_ORDER if rejections[code])
    if diagnostic:
        context += f' Основные причины исключения: {diagnostic}. Каждый исключённый профиль учтён по одной основной причине.'
    return headline + ' ' + context


def recommend(query: RecommendationQuery | Mapping[str, Any], catalog: Catalog) -> MatchResult:
    validated = _validate_query(query, catalog)
    group = sorted((profile for profile in catalog.profiles
                    if normalize_key(profile.city) == normalize_key(validated.city)
                    and normalize_key(validated.category) in {normalize_key(c) for c in profile.categories}),
                   key=lambda profile: normalize_key(profile.id))
    eligible, exclusions = [], []
    rejections: dict[RejectionCode, int] = {code: 0 for code in REJECTION_ORDER}
    for profile in group:
        reasons = _reasons(profile, validated)
        if reasons:
            exclusions.append(Exclusion(id=profile.id, reasons=reasons, primary_reason=reasons[0]))
            rejections[reasons[0]] += 1
        else:
            eligible.append(profile)
    eligible.sort(key=lambda profile: (profile.price_from_kzt, normalize_key(profile.id)))
    matches = tuple(eligible[:3])
    counts = MatchCounts(group=len(group), matched=len(eligible), shown=len(matches))
    status = 'CATEGORY_UNAVAILABLE' if not group else ('MATCHED' if eligible else 'NO_MATCHES')
    return MatchResult(
        status=status, message=_message(validated, counts, rejections), query=validated,
        catalog_version=catalog.version, ranking_version=RANKING_VERSION, counts=counts,
        matches=matches, eligible_ids=tuple(profile.id for profile in eligible),
        exclusions=tuple(exclusions), rejections=rejections,
    )
