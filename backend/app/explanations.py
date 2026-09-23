"""Deterministic, source-bound explanations. No LLM or execution of profile text."""
from decimal import Decimal
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .api_models import DataWarning, Evidence, RecommendationCard, RecommendationResponse
from .catalog import Catalog
from .matching_models import MatchResult, RecommendationQuery
from .models import Profile, decimal_text, normalize_key

FACTS_PATH = Path(__file__).parent / 'data' / 'profile_facts.json'
# Version both the reviewed facts and the rules that turn them into sentences.
EXPLANATION_VERSION = 'evidence-v2'
DECORATION = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0E\uFE0F\u200D\u20E3\u2022\u25A0\u25AA\u25CF\u231A\u231B\u2328\u23CF\u23E9-\u23F3\u23F8-\u23FA\u2B05-\u2B07\u2B1B-\u2B1C\u2B50\u2B55]')


def clean_display(value: str) -> str:
    """Only remove decorative symbols and collapse whitespace; never alter source."""
    return ' '.join(DECORATION.sub('', value).split())


def _money(value: int) -> str:
    return f'{value:,}'.replace(',', ' ')


def _hours(value: Decimal) -> str:
    # Avoid expanding huge exponents from an extended catalog into long UI strings.
    if -6 <= value.adjusted() <= 6:
        text = format(value, 'f')
        return text.rstrip('0').rstrip('.') if '.' in text else text
    return decimal_text(value)


@lru_cache(maxsize=1)
def _facts_bundle() -> tuple[dict[str, Any], str]:
    try:
        raw = FACTS_PATH.read_bytes()
        bundle = json.loads(raw)
        profiles = bundle.get('profiles')
        if bundle.get('version') != 'reviewed-facts-v1' or not isinstance(profiles, dict):
            raise ValueError('Неверная схема разметки')
        return profiles, EXPLANATION_VERSION + ':' + hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, UnicodeError, AttributeError, RecursionError):
        return {}, EXPLANATION_VERSION + ':no-reviewed-facts'


def _reviewed_entry(profile: Profile) -> dict[str, Any] | None:
    profiles, _ = _facts_bundle()
    entry = profiles.get(profile.id)
    if not isinstance(entry, dict) or entry.get('description_sha256') != hashlib.sha256(profile.description.encode('utf-8')).hexdigest():
        return None
    context = entry.get('context', {})
    if not isinstance(context, dict) or 'max_hours' not in context:
        return None
    if any(context.get(field) != (list(getattr(profile, field)) if field in ('event_formats', 'languages') else getattr(profile, field))
           for field in ('anon_name', 'city', 'event_formats', 'languages')):
        return None
    try:
        hours = context.get('max_hours')
        if (None if hours is None else Decimal(hours)) != profile.max_hours:
            return None
    except (ValueError, ArithmeticError, TypeError):
        return None
    quote = entry.get('quote')
    if quote is not None and (not isinstance(quote, str) or not quote.strip() or quote not in profile.description):
        return None
    warnings = entry.get('warnings', [])
    if not isinstance(warnings, list):
        return None
    for warning in warnings:
        if not isinstance(warning, dict) or not isinstance(warning.get('code'), str) or not isinstance(warning.get('message'), str):
            return None
        quote = warning.get('quote')
        if quote is not None and (not isinstance(quote, str) or not quote.strip() or quote not in profile.description):
            return None
    return entry


def _quote_evidence(quote: str, code: str = 'DESCRIPTION_FEATURE') -> Evidence:
    displayed = clean_display(quote)
    changed = displayed != quote
    prefix = 'Фрагмент описания (оформление очищено)' if changed else 'Точная цитата из описания'
    return Evidence(code=code, field='description', quote=quote,
                    text=f'{prefix}: «{displayed}»', display_is_cleaned=changed)


def _structured_evidence(profile: Profile, query: RecommendationQuery) -> list[Evidence]:
    date_text = query.event_date.isoformat()
    evidence = [
        Evidence(code='CITY', field='city', profile_value=profile.city, requested_value=query.city,
                 text=f'Город профиля: {clean_display(profile.city)}; город запроса: {clean_display(query.city)}.'),
        Evidence(code='CATEGORY', field='categories', profile_value=list(profile.categories), requested_value=query.category,
                 text=f'Категория «{clean_display(query.category)}» есть в профиле.'),
        Evidence(code='AVAILABLE_ON_DATE', field='busy_dates', profile_value=[d.isoformat() for d in sorted(profile.busy_dates)], requested_value=date_text,
                 text=f'{date_text} отсутствует в списке занятых дат набора; личного подтверждения подрядчика нет.'),
        Evidence(code='FORMAT', field='event_formats', profile_value=list(profile.event_formats), requested_value=query.event_format,
                 text=f'В профиле указан формат «{clean_display(query.event_format)}».'),
        Evidence(code='BUDGET', field='price_from_kzt', profile_value=profile.price_from_kzt, requested_value=query.budget_kzt,
                 text=f'Начальная цена от {_money(profile.price_from_kzt)} ₸ не выше бюджета {_money(query.budget_kzt)} ₸; итоговая стоимость не подтверждена.'),
        Evidence(code='LANGUAGE' if query.language else 'LANGUAGES', field='languages', profile_value=list(profile.languages), requested_value=query.language,
                 text=f'Языки по профилю: {clean_display(", ".join(profile.languages))}.' +
                      (f' Запрошен язык: {clean_display(query.language)}.' if query.language else ' Ограничение по языку не задано.')),
    ]
    if profile.max_hours is None:
        evidence.append(Evidence(code='DURATION_NOT_APPLICABLE', field='max_hours',
                                 requested_value=decimal_text(query.duration_hours),
                                 text='По данным профиля услуга не привязана к длительности присутствия; фильтр часов не применяется.'))
    else:
        evidence.append(Evidence(code='DURATION_LIMIT', field='max_hours', profile_value=decimal_text(profile.max_hours), requested_value=decimal_text(query.duration_hours),
                                 text=f'Лимит по профилю: {_hours(profile.max_hours)} ч.' +
                                      (f' Запрошено {_hours(query.duration_hours)} ч; проверено только непревышение максимума.' if query.duration_hours else ' Длительность в запросе не задана.')))
    return evidence


def _card(profile: Profile, query: RecommendationQuery, catalog: Catalog) -> RecommendationCard:
    evidence = _structured_evidence(profile, query)
    warnings: list[DataWarning] = []
    entry = _reviewed_entry(profile)
    quote = entry.get('quote') if entry else None
    if entry:
        for warning in entry.get('warnings', []):
            proof = _quote_evidence(warning['quote'], warning['code']) if warning.get('quote') else None
            warnings.append(DataWarning(code=warning['code'], message=clean_display(warning['message']), evidence=proof, profile_id=profile.id))
    if quote:
        fact = _quote_evidence(quote)
        evidence.append(fact)
        prefix = 'В описании указано' if not fact.display_is_cleaned else 'В описании указано (оформление очищено)'
        feature = f'{prefix}: «{clean_display(quote).rstrip(".!?")}».'
    else:
        feature = (f'В профиле указаны языки: {clean_display(", ".join(profile.languages))}'
                   if profile.languages else 'В профиле не указаны языки')
        feature += f'; форматы: {clean_display(", ".join(profile.event_formats))}'
        feature += ('; услуга не привязана к длительности присутствия.' if profile.max_hours is None
                    else f'; максимальная длительность — {_hours(profile.max_hours)} ч.')
        if not any(w.code == 'DESCRIPTION_LIMITED' for w in warnings):
            warnings.append(DataWarning(code='DESCRIPTION_LIMITED', message='Для текущей версии описания нет проверенного отличительного фрагмента; показаны только структурированные сведения.', profile_id=profile.id))
    conditions = [
        f'Начальная цена — от {_money(profile.price_from_kzt)} ₸ при бюджете {_money(query.budget_kzt)} ₸',
        f'формат «{clean_display(query.event_format)}» указан в профиле',
    ]
    if query.language is not None:
        conditions.append(f'запрошенный язык «{clean_display(query.language)}» есть в профиле')
    if query.duration_hours is not None:
        if profile.max_hours is None:
            conditions.append('услуга не привязана к длительности присутствия, поэтому фильтр часов не применяется')
        else:
            conditions.append(f'запрошенные {_hours(query.duration_hours)} ч не превышают лимит {_hours(profile.max_hours)} ч')
    conditions.append(f'дата {query.event_date.strftime("%d.%m.%Y")} свободна по календарю набора')
    fit = '; '.join(conditions) + '.'
    labels = []
    if profile.synthetic:
        labels.append('Синтетический профиль')
    if catalog.origin == 'team':
        labels.append('Профиль добавлен командой')
    elif catalog.origin == 'demo':
        labels.append('Демонстрационная синтетическая запись')
    if profile.city_imputed:
        labels.append('Город указан при подготовке датасета')
    if profile.price_imputed:
        labels.append('Начальная цена указана при подготовке датасета')
    categories = [query.category] + [c for c in profile.categories if normalize_key(c) != normalize_key(query.category)]
    return RecommendationCard(
        id=profile.id, anon_name=clean_display(profile.anon_name), category=clean_display(query.category),
        categories=[clean_display(c) for c in categories], city=clean_display(profile.city),
        price_from_kzt=profile.price_from_kzt, price_label=f'от {_money(profile.price_from_kzt)} ₸',
        event_date=query.event_date, availability_text=f'Свободен {query.event_date.strftime("%d.%m.%Y")} по календарю датасета',
        languages=[clean_display(v) for v in profile.languages], max_hours=decimal_text(profile.max_hours),
        duration_text=('Услуга не привязана к длительности присутствия' if profile.max_hours is None else f'Максимальная длительность по профилю: {_hours(profile.max_hours)} ч'),
        explanation=feature + ' ' + fit, evidence=evidence,
        synthetic=profile.synthetic, city_imputed=profile.city_imputed, price_imputed=profile.price_imputed,
        origin=catalog.origin, labels=labels, warnings=warnings,
    )


def build_response(result: MatchResult, catalog: Catalog) -> RecommendationResponse:
    cards = [_card(profile, result.query, catalog) for profile in result.matches]
    # Equal source fragments are a data limitation, not a reason to invent distinctions.
    quotes = [next((item.quote for item in card.evidence if item.code == 'DESCRIPTION_FEATURE'), None) for card in cards]
    for card, quote in zip(cards, quotes):
        if quote is not None and quotes.count(quote) > 1:
            card.warnings.append(DataWarning(code='SHARED_DESCRIPTION', message='Этот фрагмент одинаков у нескольких показанных профилей; сравнивайте подтверждённые условия.', profile_id=card.id))
    # An unknown/changed catalog can contain truly indistinguishable records.
    # Do not invent qualities or hide otherwise eligible candidates to force uniqueness.
    texts = [normalize_key(card.explanation) for card in cards]
    for card, text in zip(cards, texts):
        if texts.count(text) > 1:
            card.warnings.append(DataWarning(
                code='SHARED_EXPLANATION',
                message='Подтверждённые сведения для этого запроса совпадают с другой показанной карточкой; данных для содержательного различия недостаточно.',
                profile_id=card.id,
            ))
    warnings = [
        DataWarning(code='STARTING_PRICE', message='Цена «от» не является итоговой стоимостью заказа.'),
        DataWarning(code='DATASET_AVAILABILITY', message='Доступность известна только по календарю датасета и не подтверждена подрядчиком.'),
        DataWarning(code='ANONYMIZED_DATA', message='Каталог анонимизирован; синтетические и дополненные сведения отмечены отдельно.'),
    ]
    if catalog.origin == 'demo':
        warnings.append(DataWarning(code='DEMO_CATALOG', message='Демонстрационные синтетические данные.'))
    warnings.extend(warning for card in cards for warning in card.warnings)
    return RecommendationResponse(
        status=result.status, message=clean_display(result.message), query=result.query,
        catalog_version=result.catalog_version, ranking_version=result.ranking_version,
        explanation_version=_facts_bundle()[1], counts=result.counts,
        rejections=result.rejections, cards=cards, warnings=warnings,
        eligible_ids=result.eligible_ids, exclusions=result.exclusions,
    )
