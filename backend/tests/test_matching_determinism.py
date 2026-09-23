"""Воспроизводимость всего результата на исходных 66 профилях."""

import csv
from dataclasses import replace
from decimal import Decimal
import json
import os
from pathlib import Path
import random
import subprocess
import sys

import pytest

from app.catalog import export_jsonl, load_catalog
from app.matching import recommend


BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
ORIGINAL = ROOT / "hackathon dataset anonymized .csv"
DERIVED = ROOT / "data" / "derived" / "catalog.jsonl"
MAIN_QUERY = {
    "city": "Алматы",
    "category": "Ведущий",
    "event_date": "2026-09-30",
    "event_format": "корпоратив",
    "budget_kzt": 1_000_000,
}
QUERIES = [
    pytest.param(MAIN_QUERY, id="matched"),
    pytest.param({**MAIN_QUERY, "budget_kzt": 100_000}, id="no-matches"),
    pytest.param(
        {**MAIN_QUERY, "city": "Астана", "category": "Декоратор"},
        id="category-unavailable",
    ),
]


def serialize_result(query, catalog):
    # Не удаляем поля и не сортируем ключи: проверяем также сообщения,
    # причины, полную очередь прошедших кандидатов и порядок словарей.
    return json.dumps(
        recommend(query, catalog).model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


@pytest.fixture(scope="module")
def catalog():
    loaded = load_catalog(ORIGINAL)
    assert len(loaded.profiles) == 66
    return loaded


@pytest.mark.parametrize("query", QUERIES)
def test_repeated_calls_preserve_the_entire_result(catalog, query):
    expected = serialize_result(query, catalog)
    for _ in range(6):
        assert serialize_result(dict(query), catalog) == expected


@pytest.mark.parametrize("query", QUERIES)
def test_equivalent_duration_notations_preserve_the_entire_result(catalog, query):
    expected = serialize_result({**query, "duration_hours": 5}, catalog)
    for duration in (5.0, Decimal("5.00"), Decimal("50e-1")):
        assert serialize_result({**query, "duration_hours": duration}, catalog) == expected


@pytest.mark.parametrize("order", ["reversed", "shuffled"])
@pytest.mark.parametrize("query", QUERIES)
def test_csv_record_permutation_preserves_the_entire_result(
    tmp_path, catalog, query, order
):
    with ORIGINAL.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        rows = list(reader)
    assert len(rows) == 66
    original_rows = {row["id"]: row for row in rows}
    if order == "reversed":
        rows.reverse()
    else:
        random.Random(20260930).shuffle(rows)

    path = tmp_path / f"{order}.csv"
    # Переставляем CSV-записи, а не физические строки: полные описания
    # с кавычками и переносами строк должны оставаться нетронутыми.
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    with path.open(encoding="utf-8", newline="") as handle:
        assert {row["id"]: row for row in csv.DictReader(handle)} == original_rows

    permuted = load_catalog(path)
    assert serialize_result(query, permuted) == serialize_result(query, catalog)


@pytest.mark.parametrize("order", ["reversed", "shuffled"])
@pytest.mark.parametrize("query", QUERIES)
def test_matching_does_not_depend_on_catalog_import_sorting(catalog, query, order):
    profiles = list(catalog.profiles)
    if order == "reversed":
        profiles.reverse()
    else:
        random.Random(20260930).shuffle(profiles)
    assert tuple(profiles) != catalog.profiles
    permuted = replace(catalog, profiles=tuple(profiles))

    assert serialize_result(query, permuted) == serialize_result(query, catalog)


@pytest.mark.parametrize("query", QUERIES)
def test_original_and_derived_jsonl_preserve_the_entire_result(tmp_path, catalog, query):
    expected = serialize_result(query, catalog)
    assert serialize_result(query, load_catalog(DERIVED)) == expected

    exported = tmp_path / "exported.jsonl"
    export_jsonl(catalog, exported)
    assert serialize_result(query, load_catalog(exported)) == expected

    reversed_path = tmp_path / "reversed.jsonl"
    records = exported.read_text(encoding="utf-8").removesuffix("\n").split("\n")
    assert len(records) == 66
    reversed_path.write_text("\n".join(reversed(records)) + "\n", encoding="utf-8")
    assert serialize_result(query, load_catalog(reversed_path)) == expected


@pytest.mark.parametrize("query", QUERIES)
def test_fresh_processes_with_distinct_hash_seeds_return_identical_results(catalog, query):
    script = """
import json
from pathlib import Path
import sys

from app.catalog import load_catalog
from app.matching import recommend

catalog = load_catalog(Path(sys.argv[1]))
query = json.loads(sys.argv[2])
result = recommend(query, catalog).model_dump(mode="json")
print(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
"""
    expected = serialize_result(query, catalog) + "\n"
    outputs = []
    for seed in ("1", "987654321"):
        process = subprocess.run(
            [sys.executable, "-c", script, str(ORIGINAL), json.dumps(query)],
            cwd=BACKEND,
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            encoding="utf-8",
            check=True,
            timeout=20,
        )
        outputs.append(process.stdout)
    assert outputs[0] == outputs[1] == expected
