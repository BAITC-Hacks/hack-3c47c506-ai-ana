"""Local accounts and revocable, opaque cookie sessions backed by SQLite."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
from threading import BoundedSemaphore
import time
import uuid

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .api_models import ErrorResponse

COOKIE = 'ai_ana_session'
SESSION_SECONDS = 7 * 24 * 60 * 60
HASH_SLOTS = BoundedSemaphore(2)
LOCAL_ORIGINS = {f'http://{host}:{port}' for host in ('localhost', '127.0.0.1')
                 for port in (5173, 4173, 5174, 4174, 8000)}


class AuthError(Exception):
    def __init__(self, code: str, message: str, status: int):
        self.code, self.message, self.status = code, message, status


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(min_length=2, max_length=80)
    city: str = Field(default='', max_length=80)

    @field_validator('name', 'city', mode='before')
    @classmethod
    def clean_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError('Уберите управляющие символы из текста')
        return value


class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator('email')
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        # A deliberately bounded common email format, without claiming deliverability.
        if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", value):
            raise ValueError('Введите email в формате name@example.com')
        local = value.split('@')[0]
        if len(local) > 64 or local.startswith('.') or local.endswith('.') or '..' in local:
            raise ValueError('Проверьте email')
        return value


class RegisterInput(LoginInput, ProfileInput):
    password: str = Field(min_length=15, max_length=128)


class UserView(BaseModel):
    id: str
    email: str
    name: str
    city: str
    created_at: str


class AuthResponse(BaseModel):
    user: UserView | None
    csrf_token: str | None


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_key(password: str, salt: bytes) -> bytes:
    # OWASP scrypt minimum: N=2^17, r=8, p=1. Limit simultaneous memory use.
    with HASH_SLOTS:
        return hashlib.scrypt(password.encode(), salt=salt, n=2**17, r=8, p=1,
                              dklen=32, maxmem=256 * 1024 * 1024)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return 'scrypt$' + salt.hex() + '$' + password_key(password, salt).hex()


def verify_password(password: str, encoded: str | None) -> bool:
    # Unknown accounts still perform the same expensive password derivation.
    if encoded is None:
        password_key(password, bytes(16))
        return False
    kind, salt, expected = encoded.split('$')
    return kind == 'scrypt' and hmac.compare_digest(password_key(password, bytes.fromhex(salt)).hex(), expected)


class AuthStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL, name TEXT NOT NULL,
                    city TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
                CREATE TABLE IF NOT EXISTS auth_limits (
                    key TEXT PRIMARY KEY, count INTEGER NOT NULL, reset_at INTEGER NOT NULL
                );
            ''')
        os.chmod(path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def limit(self, keys: list[tuple[str, int]]) -> None:
        now = int(time.time())
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM auth_limits WHERE reset_at <= ?', (now,))
            for key, maximum in keys:
                key = digest(key)
                row = db.execute('SELECT count FROM auth_limits WHERE key = ?', (key,)).fetchone()
                if row and row['count'] >= maximum:
                    raise AuthError('RATE_LIMITED', 'Слишком много попыток. Попробуйте через 15 минут.', 429)
                db.execute('INSERT INTO auth_limits VALUES (?, 1, ?) ON CONFLICT(key) DO UPDATE SET count=count+1',
                           (key, now + 900))

    def current(self, token: str | None):
        if not token or len(token) > 128:
            return None
        with self.connect() as db:
            return db.execute('''SELECT users.* FROM users JOIN sessions ON users.id=sessions.user_id
                WHERE token_hash=? AND expires_at > ?''', (digest(token), int(time.time()))).fetchone()

    def revoke(self, token: str | None):
        if token:
            with self.connect() as db:
                db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(token),))


def install_auth(app: FastAPI):
    router = APIRouter(prefix='/api/auth', tags=['Account'],
                       responses={code: {'model': ErrorResponse} for code in (401, 403, 409, 422, 429, 500)})

    @app.exception_handler(AuthError)
    async def auth_error(_request: Request, exc: AuthError):
        headers = {'Cache-Control': 'no-store'}
        if exc.status == 429:
            headers['Retry-After'] = '900'
        return JSONResponse(status_code=exc.status, headers=headers,
                            content={'code': exc.code, 'message': exc.message, 'issues': []})

    @app.middleware('http')
    async def protect_auth(request: Request, call_next):
        if not request.url.path.startswith('/api/auth/'):
            return await call_next(request)
        if request.method in ('POST', 'PATCH', 'PUT', 'DELETE'):
            origin = request.headers.get('origin')
            allowed = request.app.state.auth_origins
            if (request.headers.get('x-requested-with') != 'AI-ANA'
                    or request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json'
                    or (origin is not None and origin not in allowed)):
                return await auth_error(request, AuthError('REQUEST_REJECTED', 'Обновите страницу и повторите действие.', 403))
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Vary'] = 'Cookie'
        return response

    def store(request: Request) -> AuthStore:
        return request.app.state.auth_store

    def csrf(token: str) -> str:
        return digest('ai-ana-csrf:' + token)

    def payload(row, token: str | None) -> AuthResponse:
        return AuthResponse(user=UserView(**dict(row)) if row else None,
                            csrf_token=csrf(token) if row and token else None)

    def authenticated(request: Request):
        token = request.cookies.get(COOKIE)
        user = store(request).current(token)
        if not user:
            raise AuthError('NOT_AUTHENTICATED', 'Сессия завершилась. Войдите снова.', 401)
        supplied = request.headers.get('x-csrf-token', '')
        if not re.fullmatch(r'[0-9a-f]{64}', supplied) or not hmac.compare_digest(supplied, csrf(token)):
            raise AuthError('CSRF_FAILED', 'Обновите страницу и повторите действие.', 403)
        return user

    def start_session(request: Request, response: Response, user) -> AuthResponse:
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        auth = store(request)
        with auth.connect() as db:
            db.execute('DELETE FROM sessions WHERE expires_at <= ? OR token_hash = ?',
                       (now, digest(request.cookies.get(COOKIE, ''))))
            db.execute('INSERT INTO sessions VALUES (?, ?, ?)', (digest(token), user['id'], now + SESSION_SECONDS))
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                            secure=request.app.state.auth_cookie_secure, samesite='lax', path='/api/auth')
        return payload(user, token)

    @router.get('/me', response_model=AuthResponse)
    def me(request: Request, response: Response):
        token = request.cookies.get(COOKIE)
        user = store(request).current(token)
        if token and not user:
            response.delete_cookie(COOKIE, path='/api/auth')
        return payload(user, token)

    @router.post('/register', response_model=AuthResponse, status_code=201)
    def register(body: RegisterInput, request: Request, response: Response):
        auth = store(request)
        ip = request.client.host if request.client else 'unknown'
        auth.limit([('register:' + ip, 10)])
        hashed = hash_password(body.password)
        user_id = str(uuid.uuid4())
        try:
            with auth.connect() as db:
                db.execute('INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)',
                           (user_id, body.email, hashed, body.name, body.city, datetime.now(timezone.utc).isoformat()))
                user = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        except sqlite3.IntegrityError:
            raise AuthError('ACCOUNT_EXISTS', 'Не удалось создать аккаунт с этим email. Попробуйте войти.', 409) from None
        return start_session(request, response, user)

    @router.post('/login', response_model=AuthResponse)
    def login(body: LoginInput, request: Request, response: Response):
        auth = store(request)
        ip = request.client.host if request.client else 'unknown'
        auth.limit([('login-ip:' + ip, 30), ('login-email:' + body.email, 10)])
        with auth.connect() as db:
            user = db.execute('SELECT * FROM users WHERE email=?', (body.email,)).fetchone()
        if not verify_password(body.password, user['password_hash'] if user else None):
            raise AuthError('INVALID_CREDENTIALS', 'Неверный email или пароль.', 401)
        return start_session(request, response, user)

    @router.post('/logout', response_model=AuthResponse)
    def logout(request: Request, response: Response):
        # Expired/missing sessions can be logged out idempotently; live sessions need CSRF.
        token = request.cookies.get(COOKIE)
        if store(request).current(token):
            authenticated(request)
        store(request).revoke(token)
        response.delete_cookie(COOKIE, path='/api/auth', secure=request.app.state.auth_cookie_secure,
                               httponly=True, samesite='lax')
        return AuthResponse(user=None, csrf_token=None)

    @router.patch('/profile', response_model=AuthResponse)
    def update_profile(body: ProfileInput, request: Request):
        user = authenticated(request)
        with store(request).connect() as db:
            db.execute('UPDATE users SET name=?, city=? WHERE id=?', (body.name, body.city, user['id']))
            updated = db.execute('SELECT * FROM users WHERE id=?', (user['id'],)).fetchone()
        return payload(updated, request.cookies.get(COOKIE))

    app.include_router(router)
