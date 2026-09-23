"""Exercise the developer-facing entry point, including separate error exits."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def run_cli(*args):
    return subprocess.run([sys.executable, '-m', 'app.match_cli', *args], cwd=BACKEND,
                          capture_output=True, text=True, timeout=10)


def test_cli_real_matching_result():
    proc = run_cli('--query', 'docs/queries/corporate-host.json')
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload['status'] == 'MATCHED'
    assert [profile['id'] for profile in payload['matches']] == ['HK-88430', 'HK-44923', 'HK-35215']
    assert payload['counts'] == {'group': 10, 'matched': 6, 'shown': 3}


@pytest.mark.parametrize('filename,status', [('no-matches.json', 'NO_MATCHES'), ('no-category.json', 'CATEGORY_UNAVAILABLE')])
def test_empty_business_outcomes_are_successful_cli_exits(filename, status):
    proc = run_cli('--query', 'docs/queries/' + filename)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)['status'] == status


def test_unknown_category_is_input_error(tmp_path):
    query = json.loads((BACKEND.parent / 'docs/queries/corporate-host.json').read_text())
    query['category'] = 'Нет такого значения'
    path = tmp_path / 'query.json'
    path.write_text(json.dumps(query), encoding='utf-8')
    proc = run_cli('--query', str(path))
    assert proc.returncode == 1
    assert not proc.stdout
    error = json.loads(proc.stderr)
    assert error['code'] == 'INVALID_QUERY'
    assert error['issues'][0]['field'] == 'category'


def test_catalog_failure_is_not_empty_result(tmp_path):
    proc = run_cli('--query', 'docs/queries/no-category.json', '--catalog', str(tmp_path / 'missing.csv'))
    assert proc.returncode == 1
    assert json.loads(proc.stderr)['code'] == 'CATALOG_LOAD_FAILED'
    assert not proc.stdout


@pytest.mark.parametrize('content', ['{', '[1,2]', '{"city":"\\ud800"}', '{"budget_kzt":NaN}'])
def test_malformed_query_has_diagnostic(tmp_path, content):
    path = tmp_path / 'query.json'
    path.write_text(content, encoding='utf-8')
    proc = run_cli('--query', str(path))
    assert proc.returncode == 1
    assert json.loads(proc.stderr)['code'] == 'INVALID_QUERY'
    assert 'Traceback' not in proc.stderr
