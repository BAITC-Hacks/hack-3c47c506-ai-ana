from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient

from app.main import create_app


def test_ready_means_catalog_loaded():
    with TestClient(create_app()) as client:
        health = client.get('/health')
        assert health.status_code == 200
        assert health.json()['profile_count'] == 66
        meta = client.get('/api/catalog/meta').json()
        assert meta['catalog_version'] == health.json()['catalog_version']
        assert meta['quality'] == {'synthetic': 13, 'city_imputed': 8, 'price_imputed': 18, 'null_max_hours': 9}
        assert len(meta['dictionaries']['categories']) == 17
        assert meta['origin'] == 'original'
        assert client.post('/api/recommendations', json={}).status_code == 422


def test_missing_catalog_is_technical_failure(tmp_path):
    with TestClient(create_app(tmp_path / 'missing.csv')) as client:
        for url in ['/health', '/api/catalog/meta']:
            response = client.get(url)
            assert response.status_code == 503
            assert str(tmp_path) not in response.text
            assert 'NO_MATCHES' not in response.text


def test_broken_catalog_not_ready(tmp_path):
    path = tmp_path / 'broken.jsonl'
    path.write_text('{"id":"broken"}\n', encoding='utf-8')
    with TestClient(create_app(path)) as client:
        assert client.get('/health').status_code == 503
        assert client.app.state.catalog is None
        assert client.app.state.catalog_error.issues


def test_explicit_demo_mode():
    with TestClient(create_app(Path('backend/tests/fixtures/catalog_valid.jsonl'), origin='demo')) as client:
        meta = client.get('/api/catalog/meta')
        assert meta.status_code == 200
        assert meta.json()['origin'] == 'demo'
        assert meta.json()['profile_count'] < 66


def test_cli_errors_have_nonzero_exit_and_report(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'app.cli', str(tmp_path / 'missing.csv')], capture_output=True, text=True)
    assert result.returncode == 1
    assert '"issues"' in result.stderr
    assert 'Traceback' not in result.stderr
