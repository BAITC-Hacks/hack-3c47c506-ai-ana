"""Account lifecycle, isolation, persistence and security boundaries."""
import sqlite3
import time

from fastapi.testclient import TestClient
import pytest

from app.auth import COOKIE, AuthError, AuthStore, hash_password
from app.main import create_app

HEADERS = {'X-Requested-With': 'AI-ANA', 'Content-Type': 'application/json'}
PASSWORD = 'A long test passphrase 2026!'
ACCOUNT = {'email': 'anna@example.com', 'password': PASSWORD, 'name': 'Анна', 'city': 'Алматы'}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTH_COOKIE_SECURE', 'false')
    monkeypatch.delenv('AUTH_ALLOWED_ORIGINS', raising=False)
    with TestClient(create_app(auth_db_path=tmp_path / 'accounts.sqlite3'), headers=HEADERS) as client:
        yield client


def register(client, **changes):
    response = client.post('/api/auth/register', json={**ACCOUNT, **changes})
    assert response.status_code == 201, response.text
    return response.json()


def test_registration_profile_logout_login_and_cookie_security(client):
    assert client.get('/api/auth/me').json() == {'user': None, 'csrf_token': None}
    response = client.post('/api/auth/register', json={**ACCOUNT, 'email': ' ANNA@Example.COM '})
    assert response.status_code == 201
    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=lax' in cookie and 'Path=/api/auth' in cookie
    assert response.headers['cache-control'] == 'no-store'
    body = response.json()
    assert body['user']['email'] == 'anna@example.com'
    assert set(body['user']) == {'id', 'email', 'name', 'city', 'created_at'}
    assert PASSWORD not in response.text and 'password_hash' not in response.text
    assert client.get('/api/auth/me').json() == body
    csrf = {'X-CSRF-Token': body['csrf_token']}
    updated = client.patch('/api/auth/profile', json={'name': 'Анна Новая', 'city': 'Астана'}, headers=csrf)
    assert updated.status_code == 200
    assert updated.json()['user']['city'] == 'Астана'
    old_token = client.cookies.get(COOKIE)
    assert client.post('/api/auth/logout', json={}, headers=csrf).status_code == 200
    assert client.get('/api/auth/me').json()['user'] is None
    assert client.app.state.auth_store.current(old_token) is None
    login = client.post('/api/auth/login', json={'email': ACCOUNT['email'], 'password': PASSWORD})
    assert login.status_code == 200
    assert login.json()['user']['name'] == 'Анна Новая'
    assert client.cookies.get(COOKIE) != old_token


def test_unknown_user_and_wrong_password_same_response(client):
    register(client)
    wrong = client.post('/api/auth/login', json={'email': ACCOUNT['email'], 'password': 'wrong'})
    missing = client.post('/api/auth/login', json={'email': 'missing@example.com', 'password': 'wrong'})
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json() == missing.json()
    duplicate = client.post('/api/auth/register', json={**ACCOUNT, 'email': 'ANNA@EXAMPLE.COM'})
    assert duplicate.status_code == 409


@pytest.mark.parametrize('patch', [
    {'email': 'invalid'}, {'email': 'a..b@example.com'}, {'password': 'too-short'},
    {'password': 'a' * 129}, {'name': ' '}, {'name': 'a' * 81}, {'city': 'a' * 81},
    {'name': 'Анна\nЕщё'}, {'user_id': 'someone-else'},
])
def test_registration_validation_does_not_echo_password(client, patch):
    response = client.post('/api/auth/register', json={**ACCOUNT, **patch})
    assert response.status_code == 422
    assert response.json()['code'] == 'INVALID_INPUT'
    assert PASSWORD not in response.text


def test_csrf_cross_origin_and_content_type_boundaries(client):
    assert client.post('/api/auth/register', json=ACCOUNT, headers={'X-Requested-With': ''}).status_code == 403
    assert client.post('/api/auth/register', json=ACCOUNT, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.post('/api/auth/register', content='{}', headers={'Content-Type': 'text/plain'}).status_code == 403
    data = register(client)
    profile = {'name': 'Изменено', 'city': 'Астана'}
    assert client.patch('/api/auth/profile', json=profile).status_code == 403
    assert client.post('/api/auth/logout', json={}, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    # Raw non-ASCII header bytes must be rejected rather than reaching compare_digest(str).
    assert client.patch('/api/auth/profile', json=profile,
                        headers=[(b'X-CSRF-Token', b'\xff' * 64)]).status_code == 403
    assert client.get('/api/auth/me').json() == data
    response = client.patch('/api/auth/profile', json=profile,
                            headers={'X-CSRF-Token': data['csrf_token'], 'Origin': 'http://localhost:5173'})
    assert response.status_code == 200


def test_session_expiry_rotation_and_cross_account_isolation(client):
    first = register(client)
    old_token = client.cookies.get(COOKIE)
    # Registering/login as a second user rotates only this browser's session.
    second = register(client, email='other@example.com', name='Второй')
    assert client.app.state.auth_store.current(old_token) is None
    assert first['csrf_token'] != second['csrf_token']
    assert client.patch('/api/auth/profile', json={'name': 'Взлом', 'city': ''},
                        headers={'X-CSRF-Token': first['csrf_token']}).status_code == 403
    assert client.patch('/api/auth/profile', json={'name': 'Второй новый', 'city': '', 'id': first['user']['id']},
                        headers={'X-CSRF-Token': second['csrf_token']}).status_code == 422
    assert client.patch('/api/auth/profile', json={'name': 'Второй новый', 'city': ''},
                        headers={'X-CSRF-Token': second['csrf_token']}).status_code == 200
    with client.app.state.auth_store.connect() as db:
        assert db.execute('SELECT name FROM users WHERE id=?', (first['user']['id'],)).fetchone()['name'] == 'Анна'
        db.execute('UPDATE sessions SET expires_at=?', (int(time.time()) - 1,))
    assert client.patch('/api/auth/profile', json={'name': 'Тест', 'city': ''},
                        headers={'X-CSRF-Token': second['csrf_token']}).status_code == 401
    assert client.get('/api/auth/me').json()['user'] is None
    assert client.cookies.get(COOKIE) is None


def test_accounts_sessions_survive_restart_and_storage_contains_no_plain_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTH_COOKIE_SECURE', 'false')
    path = tmp_path / 'persist.sqlite3'
    with TestClient(create_app(auth_db_path=path), headers=HEADERS) as first:
        account = register(first)
        token = first.cookies.get(COOKIE)
    with sqlite3.connect(path) as db:
        stored = db.execute('SELECT password_hash FROM users').fetchone()[0]
        assert stored.startswith('scrypt$') and PASSWORD not in stored
        assert db.execute('SELECT token_hash FROM sessions').fetchone()[0] != token
    assert path.stat().st_mode & 0o777 == 0o600
    with TestClient(create_app(auth_db_path=path), headers=HEADERS) as restarted:
        restarted.cookies.set(COOKIE, token)
        assert restarted.get('/api/auth/me').json() == account


def test_rate_limits_persist_and_expire(tmp_path):
    path = tmp_path / 'limits.sqlite3'
    auth = AuthStore(path)
    for _ in range(3):
        auth.limit([('example', 3)])
    with pytest.raises(AuthError) as caught:
        AuthStore(path).limit([('example', 3)])
    assert caught.value.status == 429
    with auth.connect() as db:
        db.execute('UPDATE auth_limits SET reset_at=?', (int(time.time()) - 1,))
    auth.limit([('example', 3)])


def test_login_rate_limit_blocks_before_hashing(client, monkeypatch):
    import app.auth as auth
    monkeypatch.setattr(auth, 'verify_password', lambda *_: False)
    for _ in range(10):
        assert client.post('/api/auth/login', json={'email': ACCOUNT['email'], 'password': 'wrong'}).status_code == 401
    response = client.post('/api/auth/login', json={'email': ACCOUNT['email'], 'password': 'wrong'})
    assert response.status_code == 429
    assert response.headers['retry-after'] == '900'


def test_secure_cookie_config(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTH_COOKIE_SECURE', 'true')
    with TestClient(create_app(auth_db_path=tmp_path / 'secure.sqlite3'), headers=HEADERS, base_url='https://testserver') as client:
        response = client.post('/api/auth/register', json=ACCOUNT)
        assert 'Secure' in response.headers['set-cookie']
        assert client.get('/api/auth/me').json()['user']['email'] == ACCOUNT['email']


def test_passwords_are_salted():
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_account_server_failure_is_generic_and_uncacheable(tmp_path, monkeypatch):
    with TestClient(create_app(auth_db_path=tmp_path / 'failure.sqlite3'),
                    raise_server_exceptions=False) as client:
        def fail(_token):
            raise RuntimeError('SECRET-internal-database-path')
        monkeypatch.setattr(client.app.state.auth_store, 'current', fail)
        response = client.get('/api/auth/me')
        assert response.status_code == 500
        assert response.headers['cache-control'] == 'no-store'
        assert 'SECRET' not in response.text
        assert 'аккаунтом' in response.json()['message']
