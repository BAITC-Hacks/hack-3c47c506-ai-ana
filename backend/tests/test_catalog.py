"""Проверки реального набора и независимых повреждённых входных файлов."""

import csv
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.catalog import CatalogError, export_jsonl, load_catalog, normalize_key


FIXTURES = Path(__file__).parent / "fixtures"
ORIGINAL = Path(__file__).resolve().parents[2] / "hackathon dataset anonymized .csv"
LIST_FIELDS = {"categories", "event_formats", "languages", "busy_dates"}


@pytest.fixture
def record():
    return json.loads((FIXTURES / "catalog_valid.jsonl").read_text().splitlines()[0])


def write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def csv_record(record):
    return {
        key: "|".join(value) if key in LIST_FIELDS else "" if value is None else str(value)
        for key, value in record.items()
    }


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def assert_issue(error, path, field, *, line=None, profile_id=None):
    """Диагностика должна позволять найти и исправить повреждённое значение."""
    issues = [issue for issue in error.issues if issue.field == field]
    assert issues, [(issue.field, issue.message) for issue in error.issues]
    issue = issues[0]
    assert str(issue.source) == str(path)
    assert issue.message
    if line is not None:
        assert issue.line == line
    if profile_id is not None:
        assert issue.profile_id == profile_id
    report = str(error)
    assert path.name in report
    assert field in report
    assert any("а" <= character.lower() <= "я" for character in report)


def test_original_catalog_keeps_all_source_profiles_and_full_descriptions():
    with ORIGINAL.open(encoding="utf-8-sig", newline="") as handle:
        source = list(csv.DictReader(handle))

    catalog = load_catalog(ORIGINAL)
    profiles = {profile.id: profile for profile in catalog.profiles}

    assert len(catalog.profiles) == len(profiles) == 66
    assert catalog.origin == "original"
    assert catalog.source_sha256 == hashlib.sha256(ORIGINAL.read_bytes()).hexdigest()
    assert sum(profile.max_hours is None for profile in profiles.values()) == 9
    assert sum(profile.synthetic for profile in profiles.values()) == 13
    assert sum(profile.city_imputed for profile in profiles.values()) == 8
    assert sum(profile.price_imputed for profile in profiles.values()) == 18
    assert len({category for profile in profiles.values() for category in profile.categories}) == 17

    for row in source:
        profile = profiles[row["id"]]
        for field in ("id", "anon_name", "city", "description"):
            assert getattr(profile, field) == row[field]
        for field in ("synthetic", "city_imputed", "price_imputed"):
            assert getattr(profile, field) is (row[field] == "True")
        assert profile.price_from_kzt == int(row["price_from_kzt"])
        assert profile.max_hours == (Decimal(row["max_hours"]) if row["max_hours"] else None)
        assert profile.busy_dates == tuple(date.fromisoformat(value) for value in row["busy_dates"].split("|"))


def test_csv_bom_multiline_quotes_lists_and_null_are_parsed_without_mutation(record):
    catalog = load_catalog(FIXTURES / "catalog_valid.csv", origin="demo")
    first, second = catalog.profiles
    assert first.description == record["description"]
    assert first.anon_name == record["anon_name"]
    assert first.categories == ("Ведущий", "Организатор")
    assert first.event_formats == ("корпоратив", "свадьба")
    assert first.languages == ("русский", "казахский")
    assert first.busy_dates == (date(2026, 9, 23), date(2026, 12, 31))
    assert first.max_hours == Decimal("2.5")
    assert first.city_imputed is False
    assert first.price_imputed is False
    assert second.max_hours is None
    assert second.busy_dates == ()
    assert catalog.origin == "demo"
    assert len(catalog.profiles) == 2  # Размер 66 не является правилом импорта.
    with pytest.raises(ValidationError):
        first.description = "Подмена исходного описания"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" \tАЛМАТЫ\u00a0 ", "алматы"),
        ("  ＡＢＣ\n  ВедУщий  ", "abc ведущий"),
        ("СВАДЬБА\t\n  И   ТОЙ", "свадьба и той"),
    ],
)
def test_comparison_normalization_is_separate_from_original_display_text(value, expected):
    assert normalize_key(value) == expected


def test_equivalent_csv_jsonl_and_row_permutations_have_same_catalog_version(tmp_path):
    csv_catalog = load_catalog(FIXTURES / "catalog_valid.csv")
    json_catalog = load_catalog(FIXTURES / "catalog_valid.jsonl")
    rows = [json.loads(line) for line in (FIXTURES / "catalog_valid.jsonl").read_text().splitlines()]
    permuted = load_catalog(write_jsonl(tmp_path / "reversed.jsonl", rows[::-1]))

    assert csv_catalog.version == json_catalog.version == permuted.version
    assert csv_catalog.source_sha256 != json_catalog.source_sha256
    assert json_catalog.source_sha256 != permuted.source_sha256
    assert {profile.id: profile for profile in csv_catalog.profiles} == {
        profile.id: profile for profile in json_catalog.profiles
    }


def test_catalog_version_changes_when_a_profile_fact_changes(tmp_path, record):
    path = write_jsonl(tmp_path / "catalog.jsonl", [record])
    initial = load_catalog(path)
    record["price_from_kzt"] += 1
    changed = load_catalog(write_jsonl(path, [record]))
    assert initial.version != changed.version
    assert initial.source_sha256 != changed.source_sha256


@pytest.mark.parametrize("origin", ["original", "team", "demo"])
def test_export_preserves_profiles_version_and_origin(tmp_path, origin):
    source = load_catalog(FIXTURES / "catalog_valid.csv", origin=origin)
    destination = tmp_path / "derived.jsonl"
    export_jsonl(source, destination)
    derived = load_catalog(destination)

    assert derived.origin == origin
    assert derived.version == source.version
    assert derived.profiles == source.profiles
    assert derived.source_sha256 == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert derived.source_sha256 != source.source_sha256
    decoded = [json.loads(line) for line in destination.read_text().splitlines()]
    assert decoded[0]["max_hours"] == 2.5
    assert not isinstance(decoded[0]["max_hours"], (str, bool))
    assert decoded[1]["max_hours"] is None
    assert decoded[1]["busy_dates"] == []


def test_conflicting_origin_cannot_silently_replace_export_provenance(tmp_path):
    source = load_catalog(FIXTURES / "catalog_valid.csv", origin="demo")
    destination = tmp_path / "derived.jsonl"
    export_jsonl(source, destination)
    with pytest.raises(CatalogError) as caught:
        load_catalog(destination, origin="team")
    assert any(issue.field == "metadata" for issue in caught.value.issues)


def test_origin_is_independent_of_synthetic_flag():
    original = load_catalog(ORIGINAL)
    assert original.origin == "original"
    assert any(profile.synthetic for profile in original.profiles)


def test_export_does_not_overwrite_an_existing_source(tmp_path, record):
    path = write_jsonl(tmp_path / "source.jsonl", [record])
    source_bytes = path.read_bytes()
    with pytest.raises(CatalogError):
        export_jsonl(load_catalog(path), path)
    assert path.read_bytes() == source_bytes


def test_changed_export_cannot_reuse_stale_provenance(tmp_path):
    catalog = load_catalog(FIXTURES / "catalog_valid.csv", origin="demo")
    path = tmp_path / "derived.jsonl"
    export_jsonl(catalog, path)
    path.write_text(path.read_text().replace("150000", "150001"), encoding="utf-8")
    with pytest.raises(CatalogError) as caught:
        load_catalog(path)
    assert any(issue.field == "metadata" for issue in caught.value.issues)


@pytest.mark.parametrize("field", ["max_hours", "busy_dates", "description"])
@pytest.mark.parametrize("format", ["csv", "jsonl"])
def test_missing_required_fields_are_not_treated_as_null_or_empty(tmp_path, record, field, format):
    del record[field]
    path = tmp_path / f"missing.{format}"
    if format == "csv":
        write_csv(path, [csv_record(record)])
    else:
        write_jsonl(path, [record])
    with pytest.raises(CatalogError) as caught:
        load_catalog(path)
    assert_issue(caught.value, path, field)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("synthetic", "false"),
        ("city_imputed", "0"),
        ("price_imputed", "yes"),
        ("price_from_kzt", "0"),
        ("price_from_kzt", "-1"),
        ("price_from_kzt", "1.5"),
        ("price_from_kzt", "NaN"),
        ("price_from_kzt", "Infinity"),
        ("max_hours", "0"),
        ("max_hours", "-0.5"),
        ("max_hours", "NaN"),
        ("max_hours", "Infinity"),
        ("busy_dates", "2026-02-30"),
        ("busy_dates", "2026-9-23"),
        ("busy_dates", "2026-09-23T00:00:00"),
        ("busy_dates", "2026-09-22"),
        ("busy_dates", "2027-01-01"),
    ],
)
def test_csv_rejects_invalid_flags_numbers_and_calendar(tmp_path, record, field, invalid):
    row = csv_record(record)
    row[field] = invalid
    path = write_csv(tmp_path / "invalid.csv", [row])
    with pytest.raises(CatalogError) as caught:
        load_catalog(path)
    assert_issue(caught.value, path, field, line=2, profile_id=record["id"])


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("synthetic", "False"),
        ("synthetic", 0),
        ("city_imputed", None),
        ("price_imputed", 1),
        ("id", 12),
        ("description", None),
        ("categories", "Ведущий"),
        ("categories", ["Ведущий", 1]),
        ("languages", None),
        ("event_formats", {"корпоратив": True}),
        ("busy_dates", None),
        ("busy_dates", "2026-09-23"),
        ("busy_dates", [20260923]),
        ("busy_dates", ["2026-09-22"]),
        ("busy_dates", ["2027-01-01"]),
        ("price_from_kzt", "150000"),
        ("price_from_kzt", True),
        ("price_from_kzt", 150000.5),
        ("price_from_kzt", 0),
        ("max_hours", "2.5"),
        ("max_hours", False),
        ("max_hours", 0),
        ("max_hours", -0.5),
    ],
)
def test_jsonl_does_not_coerce_invalid_types_or_values(tmp_path, record, field, invalid):
    record[field] = invalid
    path = write_jsonl(tmp_path / "invalid.jsonl", [record])
    with pytest.raises(CatalogError) as caught:
        load_catalog(path)
    assert_issue(caught.value, path, field, line=1)


@pytest.mark.parametrize("format", ["csv", "jsonl"])
def test_duplicate_ids_fail_the_entire_import(tmp_path, record, format):
    second = {**record, "anon_name": "Другой профиль с тем же id"}
    path = tmp_path / f"duplicate.{format}"
    if format == "csv":
        write_csv(path, [csv_record(record), csv_record(second)])
    else:
        write_jsonl(path, [record, second])
    with pytest.raises(CatalogError) as caught:
        load_catalog(path)
    # Описание CSV занимает две физические строки, поэтому повтор начинается с 4.
    assert_issue(caught.value, path, "id", line=4 if format == "csv" else 2, profile_id=record["id"])


@pytest.mark.parametrize("format", ["csv", "jsonl"])
def test_unknown_fields_report_schema_mismatch(tmp_path, record, format):
    record["unexpected_field"] = "Опечатка в схеме"
    path = tmp_path / f"unknown.{format}"
    if format == "csv":
        write_csv(path, [csv_record(record)])
    else:
        write_jsonl(path, [record])
    with pytest.raises(CatalogError) as caught:
        load_catalog(path)
    assert_issue(caught.value, path, "unexpected_field")


def test_jsonl_syntax_error_is_not_silently_skipped(tmp_path, record):
    path = write_jsonl(tmp_path / "broken.jsonl", [record])
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"id": "BROKEN",\n')
    with pytest.raises(CatalogError) as caught:
        load_catalog(path)
    assert any(issue.line == 2 and str(issue.source) == str(path) for issue in caught.value.issues)


@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "-Infinity"])
def test_jsonl_rejects_nonstandard_nonfinite_numbers(tmp_path, record, invalid):
    raw = json.dumps(record, ensure_ascii=False).replace('"max_hours": 2.5', f'"max_hours": {invalid}')
    path = tmp_path / "nonfinite.jsonl"
    path.write_text(raw + "\n", encoding="utf-8")
    with pytest.raises(CatalogError) as caught:
        load_catalog(path)
    assert any(issue.line == 1 and str(issue.source) == str(path) for issue in caught.value.issues)


def test_decimal_duration_survives_export_without_rounding(tmp_path, record):
    row = csv_record(record)
    row["max_hours"] = "2.123456789012345678901234567890123456789"
    catalog = load_catalog(write_csv(tmp_path / "precise.csv", [row]))
    destination = tmp_path / "precise.jsonl"
    export_jsonl(catalog, destination)
    exported = load_catalog(destination)
    assert exported.profiles[0].max_hours == Decimal(row["max_hours"])
    assert exported.version == catalog.version


def test_unicode_line_separators_inside_json_strings_are_not_jsonl_record_boundaries(tmp_path, record):
    record["description"] = "Первая часть\u2028вторая часть\u0085третья часть"
    path = write_jsonl(tmp_path / "unicode.jsonl", [record])
    catalog = load_catalog(path)
    assert len(catalog.profiles) == 1
    assert catalog.profiles[0].description == record["description"]


def test_jsonl_invalid_unicode_is_reported_instead_of_crashing_version_hash(tmp_path, record):
    record["description"] = "\ud800"
    path = tmp_path / "invalid-unicode.jsonl"
    # JSON-escape представляет некорректную одиночную суррогатную кодовую точку.
    path.write_text(json.dumps(record, ensure_ascii=True) + "\n", encoding="utf-8")
    with pytest.raises(CatalogError) as caught:
        load_catalog(path)
    assert_issue(caught.value, path, "json", line=1)


def test_jsonl_decimal_exponent_overflow_has_a_catalog_diagnostic(tmp_path, record):
    path = tmp_path / "decimal-overflow.jsonl"
    raw = json.dumps(record).replace('"max_hours": 2.5', '"max_hours": 1e9999999999999999999999999999')
    path.write_text(raw + "\n", encoding="utf-8")
    with pytest.raises(CatalogError) as caught:
        load_catalog(path)
    assert_issue(caught.value, path, "json", line=1)


@pytest.mark.parametrize(
    "spellings",
    [
        ("2.5", "2.5000", "250e-2"),
        ("2500", "25e2"),
        ("1e1000000", "10e999999"),
    ],
)
def test_decimal_exports_are_compact_and_version_ignores_number_notation(tmp_path, record, spellings):
    versions = set()
    for index, spelling in enumerate(spellings):
        row = csv_record(record)
        row["max_hours"] = spelling
        catalog = load_catalog(write_csv(tmp_path / f"notation-{index}.csv", [row]))
        destination = tmp_path / f"notation-{index}.jsonl"
        export_jsonl(catalog, destination)
        assert destination.stat().st_size < 2000
        reloaded = load_catalog(destination)
        assert reloaded.profiles[0].max_hours == Decimal(spelling)
        assert reloaded.version == catalog.version
        versions.add(catalog.version)
    assert len(versions) == 1


def test_deeply_nested_metadata_is_catalog_error(tmp_path):
    source = Path(__file__).parent / 'fixtures' / 'catalog_valid.jsonl'
    target = tmp_path / 'catalog.jsonl'
    target.write_bytes(source.read_bytes())
    target.with_name(target.name + '.meta.json').write_text('[' * 2000 + '0' + ']' * 2000, encoding='utf-8')
    with pytest.raises(CatalogError) as error:
        load_catalog(target)
    assert error.value.issues[0].field == 'metadata'
