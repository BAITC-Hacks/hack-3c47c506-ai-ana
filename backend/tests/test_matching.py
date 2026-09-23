"""Фильтры, диагностика и контрольные запросы к исходным 66 профилям."""

from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

import pytest

from app.catalog import load_catalog
from app.matching import RANKING_VERSION, recommend
from app.matching_models import QueryValidationError, RecommendationQuery
from app.models import normalize_key


ORIGINAL = Path(__file__).resolve().parents[2] / "hackathon dataset anonymized .csv"
REASONS = (
    "BUSY_ON_DATE",
    "UNSUPPORTED_FORMAT",
    "OVER_BUDGET",
    "UNSUPPORTED_LANGUAGE",
    "DURATION_EXCEEDED",
)


def profile(ident="MATCH-001", **changes):
    record = {
        "id": ident,
        "anon_name": "Тестовый ведущий",
        "categories": ["Ведущий"],
        "city": "Алматы",
        "price_from_kzt": 100_000,
        "event_formats": ["корпоратив"],
        "languages": ["русский"],
        "max_hours": 2.5,
        "busy_dates": [],
        "description": "Отдельная синтетическая фикстура для проверки подбора.",
        "synthetic": True,
        "city_imputed": False,
        "price_imputed": False,
    }
    record.update(changes)
    return record


def dictionary_profile():
    """Глобальные справочники не зависят от выбранной группы город + категория."""
    return profile(
        "DICTIONARIES",
        city="Астана",
        categories=["Фотограф"],
        event_formats=["свадьба", "той", "корпоратив", "конференция", "юбилей", "день рождения"],
        languages=["русский", "казахский", "английский"],
    )


def query(**changes):
    data = {
        "city": "Алматы",
        "category": "Ведущий",
        "event_date": "2026-09-23",
        "event_format": "корпоратив",
        "budget_kzt": 100_000,
    }
    data.update(changes)
    return data


@pytest.fixture
def catalog_factory(tmp_path):
    serial = 0

    def create(*records, origin="demo"):
        nonlocal serial
        serial += 1
        path = tmp_path / f"matching-{serial}.jsonl"
        path.write_text(
            "".join(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n" for record in records),
            encoding="utf-8",
        )
        return load_catalog(path, origin=origin)

    return create


@pytest.fixture
def catalog(catalog_factory):
    return catalog_factory(profile(), dictionary_profile())


@pytest.fixture(scope="module")
def original_catalog():
    return load_catalog(ORIGINAL)


def assert_balanced(result):
    assert set(result.rejections) == set(REASONS)
    assert all(type(count) is int and count >= 0 for count in result.rejections.values())
    assert result.counts.group == result.counts.matched + sum(result.rejections.values())
    assert result.counts.matched == len(result.eligible_ids)
    assert result.counts.shown == len(result.matches) == min(3, result.counts.matched)
    assert len(result.exclusions) == result.counts.group - result.counts.matched
    assert len(result.eligible_ids) == len(set(result.eligible_ids))
    assert tuple(p.id for p in result.matches) == result.eligible_ids[:3]
    assert result.message


@pytest.mark.parametrize("count", [1, 2, 3, 5])
def test_return_count_and_top_three_follow_full_filtering(catalog_factory, count):
    rows = [profile(f"FIT-{index}", price_from_kzt=10_000 * index) for index in range(count, 0, -1)]
    # A cheaper profile still cannot occupy a result slot when busy.
    rows.append(profile("CHEAP-BUSY", price_from_kzt=1, busy_dates=["2026-09-23"]))
    result = recommend(query(), catalog_factory(*rows))

    assert result.status == "MATCHED"
    assert result.counts.group == count + 1
    assert result.counts.matched == count
    assert result.eligible_ids == tuple(f"FIT-{index}" for index in range(1, count + 1))
    assert result.rejections["BUSY_ON_DATE"] == 1
    assert str(count) in result.message
    if count > 3:
        assert "3" in result.message
    assert_balanced(result)


def test_small_group_without_rejections_is_reported_honestly(catalog_factory):
    result = recommend(query(), catalog_factory(profile("FIRST"), profile("SECOND")))

    assert result.counts.group == result.counts.matched == result.counts.shown == 2
    assert result.exclusions == ()
    assert not any(result.rejections.values())
    assert "2" in result.message
    assert_balanced(result)


def test_all_reasons_are_saved_but_each_exclusion_counts_once(catalog_factory):
    rows = []
    for index, primary in enumerate(REASONS):
        rows.append(profile(
            primary,
            busy_dates=["2026-09-23"] if index == 0 else [],
            event_formats=["свадьба"] if index <= 1 else ["корпоратив"],
            price_from_kzt=100_001 if index <= 2 else 100_000,
            languages=["русский"] if index <= 3 else ["казахский"],
            max_hours=2.49,
        ))
    rows += [profile("ELIGIBLE", languages=["казахский"]), dictionary_profile()]
    result = recommend(query(language="казахский", duration_hours=2.5), catalog_factory(*rows))

    assert result.status == "MATCHED"
    assert result.counts.group == 6
    assert result.eligible_ids == ("ELIGIBLE",)
    exclusions = {excluded.id: excluded for excluded in result.exclusions}
    for index, primary in enumerate(REASONS):
        assert exclusions[primary].reasons == REASONS[index:]
        assert exclusions[primary].primary_reason == primary
    assert result.rejections == dict.fromkeys(REASONS, 1)
    assert_balanced(result)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"budget_kzt": 99_999}, "OVER_BUDGET"),
        ({"event_format": "свадьба"}, "UNSUPPORTED_FORMAT"),
        ({"language": "казахский"}, "UNSUPPORTED_LANGUAGE"),
        ({"duration_hours": Decimal("2.50000000000000000001")}, "DURATION_EXCEEDED"),
    ],
)
def test_individual_rejections_use_exact_structured_values(catalog, changes, expected):
    result = recommend(query(**changes), catalog)
    assert result.status == "NO_MATCHES"
    assert result.exclusions[0].reasons == (expected,)
    assert result.exclusions[0].primary_reason == expected
    assert_balanced(result)


def test_equal_budget_and_duration_are_inclusive(catalog):
    result = recommend(query(duration_hours=Decimal("2.50")), catalog)
    assert result.status == "MATCHED"
    assert result.matches[0].price_from_kzt == result.query.budget_kzt
    assert result.matches[0].max_hours == result.query.duration_hours
    assert_balanced(result)


@pytest.mark.parametrize("duration", [None, "", " \t\n "])
@pytest.mark.parametrize("language", [None, "", " \t\n "])
def test_empty_optional_fields_remove_constraints(catalog, duration, language):
    result = recommend(query(duration_hours=duration, language=language), catalog)
    assert result.status == "MATCHED"
    assert result.query.duration_hours is None
    assert result.query.language is None


def test_omitted_duration_does_not_filter_short_services(catalog_factory):
    result = recommend(query(), catalog_factory(profile(max_hours=0.01)))
    assert result.status == "MATCHED"
    assert result.query.duration_hours is None


def test_null_duration_is_not_zero_and_is_not_a_hidden_time_limit(catalog_factory):
    catalog = catalog_factory(profile("NO-PRESENCE", max_hours=None), profile("SHORT", max_hours=2.5))
    result = recommend(query(duration_hours=1_000), catalog)
    assert result.eligible_ids == ("NO-PRESENCE",)
    assert result.matches[0].max_hours is None
    assert result.rejections["DURATION_EXCEEDED"] == 1
    assert_balanced(result)


@pytest.mark.parametrize("category", ["Банкетный зал", "Отель", "Загородная площадка"])
def test_venues_obey_the_same_busy_calendar(catalog_factory, category):
    catalog = catalog_factory(profile(categories=[category], busy_dates=["2026-09-23"], max_hours=None))
    busy = recommend(query(category=category, duration_hours=8), catalog)
    free = recommend(query(category=category, duration_hours=8, event_date="2026-09-24"), catalog)

    assert busy.status == "NO_MATCHES"
    assert busy.exclusions[0].reasons == ("BUSY_ON_DATE",)
    assert free.status == "MATCHED"
    assert free.matches[0] is catalog.profiles[0]
    assert_balanced(busy)
    assert_balanced(free)


def test_multiple_categories_match_each_category_without_duplicates(catalog_factory):
    catalog = catalog_factory(profile(categories=["Ведущий", "Фотограф", "Видеограф"]))
    for category in catalog.profiles[0].categories:
        result = recommend(query(category=category), catalog)
        assert result.eligible_ids == ("MATCH-001",)
        assert result.counts.group == 1
        assert result.matches[0].categories == ("Ведущий", "Фотограф", "Видеограф")
        assert_balanced(result)


def test_known_category_missing_in_known_city_is_a_business_result(catalog):
    result = recommend(query(category="Фотограф"), catalog)
    assert result.status == "CATEGORY_UNAVAILABLE"
    assert result.counts.group == result.counts.matched == result.counts.shown == 0
    assert result.matches == result.eligible_ids == result.exclusions == ()
    assert "каталог" in result.message.lower()
    assert_balanced(result)


def test_no_other_city_or_category_is_added_to_fill_three_cards(catalog_factory):
    catalog = catalog_factory(
        profile("ONLY-MATCH"),
        profile("OTHER-CITY", city="Астана"),
        profile("OTHER-CATEGORY", categories=["Фотограф"]),
    )
    result = recommend(query(), catalog)
    assert result.eligible_ids == ("ONLY-MATCH",)
    assert result.counts.group == 1
    assert_balanced(result)


def test_nfkc_whitespace_and_case_normalization_preserves_profiles(catalog_factory):
    source = profile(
        "ＩＤ－01", city=" АЛМАТЫ\u00a0", categories=["  DJ\u00a0 Ведущий  "],
        event_formats=["  ДЕНЬ\n РОЖДЕНИЯ "], languages=[" РУССКИЙ\t"],
    )
    catalog = catalog_factory(source)
    result = recommend(query(
        city="\tалматы ", category="ｄｊ   ведущий", event_format=" день   рождения ", language=" русский ",
    ), catalog)

    assert result.status == "MATCHED"
    assert result.matches[0] is catalog.profiles[0]
    assert result.matches[0].city == source["city"]
    assert result.matches[0].categories == tuple(source["categories"])
    assert normalize_key(result.query.category) == "dj ведущий"
    assert normalize_key(result.query.event_format) == "день рождения"
    assert normalize_key(result.query.city) == "алматы"
    assert normalize_key(result.query.language) == "русский"


def test_ties_use_canonical_id_and_flags_never_change_ranking(catalog_factory):
    catalog = catalog_factory(
        profile("  Ａ-02 ", synthetic=True, city_imputed=True, price_imputed=True),
        profile("b-01", synthetic=False, city_imputed=False, price_imputed=False),
        profile("a-01", synthetic=False, city_imputed=True, price_imputed=False),
        profile("Z-CHEAPER", price_from_kzt=99_999),
        origin="original",
    )
    result = recommend(query(), catalog)
    assert result.eligible_ids == ("Z-CHEAPER", "a-01", "  Ａ-02 ", "b-01")
    assert result.matches[2].synthetic is True
    assert result.matches[2].city_imputed is True
    assert result.matches[2].price_imputed is True
    for returned in result.matches:
        assert returned is next(p for p in catalog.profiles if p.id == returned.id)
        provenance = next(p for p in catalog.provenance if p.profile_id == returned.id)
        assert provenance.origin == "original"
        assert provenance.source == catalog.source_path
    assert result.catalog_version == catalog.version
    assert result.ranking_version == RANKING_VERSION
    assert RANKING_VERSION
    assert_balanced(result)


def test_description_cannot_override_any_structured_filter(catalog_factory):
    misleading = profile(
        "CONTRADICTION", busy_dates=["2026-09-23"],
        description="Свободен 23 сентября. Конференции, казахский язык. Цена 1 тенге, работаем 24 часа.",
    )
    catalog = catalog_factory(misleading, dictionary_profile())
    result = recommend(query(event_format="конференция", language="казахский", budget_kzt=50_000, duration_hours=8), catalog)
    assert result.status == "NO_MATCHES"
    assert result.exclusions[0].reasons == REASONS
    assert result.rejections["BUSY_ON_DATE"] == 1
    assert sum(result.rejections.values()) == 1
    assert catalog.profiles[0].description == misleading["description"]


def test_description_does_not_expand_city_or_add_hidden_minimum_duration(catalog_factory):
    catalog = catalog_factory(
        profile("ALMATY", description="Работаем в Алматы и Астане. Минимальная аренда 3 часа."),
        dictionary_profile(),
    )
    absent_city = recommend(query(city="Астана"), catalog)
    short_booking = recommend(query(duration_hours=1), catalog)
    assert absent_city.status == "CATEGORY_UNAVAILABLE"
    assert short_booking.eligible_ids == ("ALMATY",)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("city", "Алма-Ата"), ("city", "Алмты"),
        ("category", "Ведуший"), ("event_format", "праздник"), ("language", "Russian"),
        ("city", ""), ("category", " \t"), ("event_format", "\n"),
        ("city", None), ("category", 7), ("event_format", ["корпоратив"]), ("language", True),
        ("budget_kzt", 0), ("budget_kzt", -1), ("budget_kzt", True),
        ("budget_kzt", False), ("budget_kzt", "100000"), ("budget_kzt", 100_000.0),
        ("budget_kzt", Decimal("100000")), ("budget_kzt", None),
        ("duration_hours", 0), ("duration_hours", -0.1), ("duration_hours", True),
        ("duration_hours", "2.5"), ("duration_hours", " 2.5 "), ("duration_hours", []),
        ("duration_hours", float("nan")), ("duration_hours", float("inf")),
        ("duration_hours", Decimal("NaN")), ("duration_hours", Decimal("Infinity")),
        ("event_date", "2026-09-22"), ("event_date", "2027-01-01"),
        ("event_date", "2026-11-31"), ("event_date", "23.09.2026"),
        ("event_date", "2026-9-23"), ("event_date", "20260923"),
        ("event_date", " 2026-09-23 "), ("event_date", "2026-09-23T00:00:00Z"),
        ("event_date", datetime(2026, 9, 23)), ("event_date", 1_790_121_600),
        ("event_date", None), ("event_date", True),
    ],
)
def test_invalid_queries_raise_field_errors_not_business_status(catalog, field, value):
    with pytest.raises(QueryValidationError) as caught:
        recommend(query(**{field: value}), catalog)
    issues = [issue for issue in caught.value.issues if issue.field == field]
    assert issues, [(issue.field, issue.message) for issue in caught.value.issues]
    assert all(issue.message for issue in issues)
    assert any("а" <= char.lower() <= "я" for char in str(caught.value))


@pytest.mark.parametrize("field", ["city", "category", "event_date", "event_format", "budget_kzt"])
def test_missing_required_query_field_is_reported(catalog, field):
    raw = query()
    del raw[field]
    with pytest.raises(QueryValidationError) as caught:
        recommend(raw, catalog)
    assert any(issue.field == field for issue in caught.value.issues)


@pytest.mark.parametrize("field,value", [("city", "Астана"), ("event_format", "свадьба"), ("language", "казахский")])
def test_global_dictionaries_are_taken_from_current_catalog(catalog_factory, field, value):
    # Values allowed by the general data schema can still be absent from this catalog.
    tiny_catalog = catalog_factory(profile())
    with pytest.raises(QueryValidationError) as caught:
        recommend(query(**{field: value}), tiny_catalog)
    assert any(issue.field == field for issue in caught.value.issues)


def test_typed_query_still_validates_catalog_dictionary(catalog):
    typed = RecommendationQuery(**query(category="Нет такой категории"))
    with pytest.raises(QueryValidationError) as caught:
        recommend(typed, catalog)
    assert any(issue.field == "category" for issue in caught.value.issues)


@pytest.mark.parametrize("field,value", [("budget_kzt", True), ("duration_hours", 0), ("event_date", datetime(2026, 9, 23))])
def test_modified_typed_query_cannot_bypass_input_validation(catalog, field, value):
    typed = RecommendationQuery(**query()).model_copy(update={field: value})
    with pytest.raises(QueryValidationError) as caught:
        recommend(typed, catalog)
    assert any(issue.field == field for issue in caught.value.issues)


@pytest.mark.parametrize("raw", [None, [], "not a query"])
def test_non_object_query_returns_clear_validation_error(catalog, raw):
    with pytest.raises(QueryValidationError) as caught:
        recommend(raw, catalog)
    assert any(issue.field == "query" and issue.message for issue in caught.value.issues)


def test_validation_reports_multiple_fields_together_and_rejects_extra_fields(catalog):
    with pytest.raises(QueryValidationError) as caught:
        recommend(query(budget_kzt=0, event_date="2026-09-22", guests=100), catalog)
    assert {issue.field for issue in caught.value.issues} == {"budget_kzt", "event_date", "guests"}


@pytest.mark.parametrize("event_date", ["2026-09-23", "2026-12-31", date(2026, 9, 23), date(2026, 12, 31)])
@pytest.mark.parametrize("duration", [1, 2.5, Decimal("2.5")])
def test_inclusive_calendar_and_numeric_duration_inputs(catalog, event_date, duration):
    result = recommend(query(event_date=event_date, duration_hours=duration, budget_kzt=1), catalog)
    assert type(result.query.event_date) is date
    assert type(result.query.budget_kzt) is int
    assert result.query.duration_hours == Decimal(str(duration))
    assert result.status == "NO_MATCHES"  # Small positive budgets are valid input.
    assert result.exclusions[0].reasons == ("OVER_BUDGET",)


@pytest.mark.parametrize(
    ("changes", "status", "group", "matched", "shown"),
    [
        ({"event_date": "2026-09-30", "budget_kzt": 1_000_000}, "MATCHED", 10, 6, ("HK-88430", "HK-44923", "HK-35215")),
        ({"event_date": "2026-10-01", "budget_kzt": 1_000_000}, "MATCHED", 10, 2, ("HK-88430", "HK-44923")),
        ({"category": "Декоратор", "budget_kzt": 2_500_000, "duration_hours": 5}, "MATCHED", 3, 2, ("HK-11484", "HK-90004")),
        ({"event_date": "2026-09-30"}, "NO_MATCHES", 10, 0, ()),
        ({"city": "Астана", "category": "Декоратор", "budget_kzt": 2_500_000}, "CATEGORY_UNAVAILABLE", 0, 0, ()),
        ({"city": "Астана", "category": "Отель", "budget_kzt": 3_000_000, "duration_hours": 5}, "MATCHED", 1, 1, ("HK-90012",)),
        ({"city": "Астана", "category": "Отель", "budget_kzt": 3_000_000, "duration_hours": 5, "event_date": "2026-09-25"}, "NO_MATCHES", 1, 0, ()),
    ],
    ids=["dense-category", "date-change", "rare-and-null", "all-rejected", "category-unavailable", "free-hotel", "busy-hotel"],
)
def test_seven_expected_scenarios_on_original_csv(original_catalog, changes, status, group, matched, shown):
    result = recommend(query(**changes), original_catalog)
    assert result.status == status
    assert result.counts.group == group
    assert result.counts.matched == matched
    assert tuple(p.id for p in result.matches) == shown
    assert result.catalog_version == original_catalog.version
    assert_balanced(result)


def test_original_low_budget_primary_reasons_are_exact(original_catalog):
    result = recommend(query(event_date="2026-09-30"), original_catalog)
    assert result.rejections == {
        "BUSY_ON_DATE": 1,
        "UNSUPPORTED_FORMAT": 1,
        "OVER_BUDGET": 8,
        "UNSUPPORTED_LANGUAGE": 0,
        "DURATION_EXCEEDED": 0,
    }


def test_original_synthetic_and_imputed_fields_keep_original_provenance(original_catalog):
    hotel = recommend(query(city="Астана", category="Отель", budget_kzt=3_000_000, duration_hours=5), original_catalog).matches[0]
    decorator_result = recommend(query(category="Декоратор", budget_kzt=2_500_000, duration_hours=5), original_catalog)
    decorator = next(p for p in decorator_result.matches if p.id == "HK-90004")
    assert hotel.id == "HK-90012"
    assert hotel.price_from_kzt == 2_800_000
    assert hotel.synthetic is hotel.price_imputed is True
    assert decorator.synthetic is True
    assert all(p.max_hours is None for p in decorator_result.matches)
    for profile_id in (hotel.id, decorator.id):
        provenance = next(p for p in original_catalog.provenance if p.profile_id == profile_id)
        assert provenance.origin == "original"
        assert Path(provenance.source) == ORIGINAL


def test_original_conference_mention_does_not_expand_kikis_formats(original_catalog):
    result = recommend(query(event_date="2026-09-30", event_format="конференция", budget_kzt=10_000_000), original_catalog)
    kiki = next(item for item in result.exclusions if item.id == "HK-35215")
    assert "UNSUPPORTED_FORMAT" in kiki.reasons
    assert "HK-35215" not in result.eligible_ids


def test_original_repertoire_does_not_add_service_language(original_catalog):
    target = next(p for p in original_catalog.profiles if p.id == "HK-31819")
    free_date = next(date(2026, 10, day) for day in range(1, 32) if date(2026, 10, day) not in target.busy_dates)
    result = recommend(query(city=target.city, category=target.categories[0], event_date=free_date, event_format=target.event_formats[0], language="казахский", budget_kzt=10_000_000), original_catalog)
    excluded = next(p for p in result.exclusions if p.id == target.id)
    assert excluded.reasons == ("UNSUPPORTED_LANGUAGE",)


def test_original_language_list_is_not_narrowed_by_description(original_catalog):
    target = next(p for p in original_catalog.profiles if p.id == "HK-77838")
    free_date = next(date(2026, 10, day) for day in range(1, 32) if date(2026, 10, day) not in target.busy_dates)
    result = recommend(query(city=target.city, category=target.categories[0], event_date=free_date, event_format=target.event_formats[0], language="русский", budget_kzt=10_000_000), original_catalog)
    assert target.id in result.eligible_ids
