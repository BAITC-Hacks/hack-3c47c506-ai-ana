"""Public API behavior and its documented frontend contract."""

from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import app.main as server
from app.main import create_app


QUERY = {
    'city': 'Алматы', 'category': 'Ведущий', 'event_date': '2026-09-30',
    'event_format': 'корпоратив', 'budget_kzt': 1_000_000,
}


@pytest.fixture(scope='module')
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def test_api_returns_cards_and_three_distinct_business_outcomes(client):
    scenarios = [
        (QUERY, 'MATCHED', ['HK-88430', 'HK-44923', 'HK-35215']),
        ({**QUERY, 'budget_kzt': 100_000}, 'NO_MATCHES', []),
        ({**QUERY, 'city': 'Астана', 'category': 'Декоратор'}, 'CATEGORY_UNAVAILABLE', []),
    ]
    for query, status, expected_ids in scenarios:
        result = client.post('/api/recommendations', json=query)
        assert result.status_code == 200, result.text
        data = result.json()
        assert data['status'] == status
        assert [card['id'] for card in data['cards']] == expected_ids
        assert {'query', 'catalog_version', 'ranking_version', 'explanation_version', 'warnings',
                'message', 'counts', 'rejections', 'eligible_ids', 'exclusions'} <= data.keys()
        assert data['counts']['group'] == data['counts']['matched'] + sum(data['rejections'].values())
        assert data['counts']['shown'] == len(data['cards'])
        assert data['message']
    result = client.post('/api/recommendations', json=QUERY).json()
    assert result['query']['event_date'] == QUERY['event_date']
    assert result['query']['duration_hours'] is None
    assert isinstance(result['cards'][0]['price_from_kzt'], int)
    assert isinstance(result['cards'][0]['max_hours'], str)
    assert result['catalog_version'] == client.get('/api/catalog/meta').json()['catalog_version']


def test_changing_date_updates_cards_and_busy_exclusions(client):
    response = client.post('/api/recommendations', json={**QUERY, 'event_date': '2026-10-01'})
    assert response.status_code == 200
    data = response.json()
    assert [card['id'] for card in data['cards']] == ['HK-88430', 'HK-44923']
    assert next(item for item in data['exclusions'] if item['id'] == 'HK-35215')['primary_reason'] == 'BUSY_ON_DATE'
    assert all(card['event_date'] == '2026-10-01' for card in data['cards'])


def test_invalid_requests_return_actionable_errors_without_internal_values(client):
    cases = [
        ({}, 'city'),
        ({**QUERY, 'budget_kzt': True}, 'budget_kzt'),
        ({**QUERY, 'budget_kzt': 9_007_199_254_740_992}, 'budget_kzt'),
        ({**QUERY, 'budget_kzt': 1_000_000.5}, 'budget_kzt'),
        ({**QUERY, 'duration_hours': '2.5'}, 'duration_hours'),
        ({**QUERY, 'city': 'Тайный город XYZ-PRIVATE'}, 'city'),
        ({**QUERY, 'event_date': '2026-09-22'}, 'event_date'),
        ({**QUERY, 'extra': 'XYZ-PRIVATE'}, 'extra'),
    ]
    for query, field in cases:
        response = client.post('/api/recommendations', json=query)
        assert response.status_code == 422, response.text
        data = response.json()
        assert data['code'] == 'INVALID_QUERY'
        assert data['message'] and data['issues']
        assert any(item['field'] == field for item in data['issues'])
        assert all(item['message'] for item in data['issues'])
        assert 'XYZ-PRIVATE' not in response.text
        assert 'Traceback' not in response.text
    for body in ('{broken', '[1,2]', 'null'):
        response = client.post('/api/recommendations', content=body, headers={'Content-Type': 'application/json'})
        assert response.status_code == 422
        assert response.json()['code'] == 'INVALID_QUERY'
        assert response.json()['issues']


def test_optional_fields_and_numeric_duration_use_the_documented_contract(client):
    baseline = client.post('/api/recommendations', json=QUERY).json()
    for value in (None, ''):
        result = client.post('/api/recommendations', json={**QUERY, 'duration_hours': value, 'language': value})
        assert result.status_code == 200, result.text
        assert result.json() == baseline
    result = client.post('/api/recommendations', json={**QUERY, 'duration_hours': 1.25, 'language': 'русский'})
    assert result.status_code == 200, result.text
    assert Decimal(result.json()['query']['duration_hours']) == Decimal('1.25')
    assert result.json()['query']['language'] == 'русский'


def test_missing_catalog_is_a_service_error_not_a_business_outcome(tmp_path):
    with TestClient(create_app(tmp_path / 'missing.csv')) as client:
        result = client.post('/api/recommendations', json=QUERY)
        assert result.status_code == 503
        assert result.json()['code'] == 'CATALOG_LOAD_FAILED'
        assert 'NO_MATCHES' not in result.text
        assert str(tmp_path) not in result.text


def test_unexpected_failure_has_a_generic_error_without_traceback(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError('XYZ-PRIVATE /tmp/internal-file.py')

    monkeypatch.setattr(server, 'build_response', broken)
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        result = client.post('/api/recommendations', json=QUERY)
    assert result.status_code == 500
    assert result.json()['message']
    assert result.json()['code']
    assert 'XYZ-PRIVATE' not in result.text
    assert 'Traceback' not in result.text
    assert '/tmp/internal-file' not in result.text


def test_api_bytes_match_across_original_csv_and_derived_jsonl(client):
    baseline = client.post('/api/recommendations', json=QUERY).content
    assert client.post('/api/recommendations', json=dict(QUERY)).content == baseline
    root = Path(__file__).resolve().parents[2]
    with TestClient(create_app(root / 'data/derived/catalog.jsonl')) as derived:
        assert derived.post('/api/recommendations', json=QUERY).content == baseline


def test_openapi_declares_input_and_public_response_contract(client):
    document = client.get('/openapi.json').json()
    operation = document['paths']['/api/recommendations']['post']
    schemas = document['components']['schemas']

    def resolve(schema):
        if '$ref' in schema:
            return schemas[schema['$ref'].rsplit('/', 1)[1]]
        return schema

    request = resolve(operation['requestBody']['content']['application/json']['schema'])
    assert {'city', 'category', 'event_date', 'event_format', 'budget_kzt'} <= set(request['required'])
    assert request['properties']['budget_kzt']['type'] == 'integer'
    assert request['additionalProperties'] is False
    duration = request['properties']['duration_hours']
    assert any(item.get('type') == 'number' for item in duration.get('anyOf', [duration]))
    response = resolve(operation['responses']['200']['content']['application/json']['schema'])
    assert {'status', 'message', 'query', 'cards', 'warnings', 'counts', 'explanation_version'} <= response['properties'].keys()
    card = resolve(response['properties']['cards']['items'])
    assert {'id', 'category', 'categories', 'explanation', 'evidence', 'labels', 'origin', 'warnings'} <= card['properties'].keys()
    assert card['properties']['price_from_kzt']['type'] == 'integer'
    assert {'200', '422', '500', '503'} <= operation['responses'].keys()
