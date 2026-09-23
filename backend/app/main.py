"""Catalog readiness and deterministic recommendations with evidence."""
from contextlib import asynccontextmanager
from dataclasses import asdict
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api_models import CatalogMetadata, ErrorResponse, HealthResponse, RecommendationRequest, RecommendationResponse
from .catalog import CatalogError, load_catalog
from .explanations import build_response, clean_display
from .matching import recommend
from .matching_models import QueryValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = PROJECT_ROOT / 'hackathon dataset anonymized .csv'
logger = logging.getLogger(__name__)


def error_response(code: str, message: str, status: int, issues: list[dict] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={'code': code, 'message': message, 'issues': issues or []})


def create_app(catalog_path: Path | None = None, origin: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configured = catalog_path or Path(os.environ.get('CATALOG_PATH', str(DEFAULT_CATALOG)))
        path = configured if configured.is_absolute() else PROJECT_ROOT / configured
        configured_origin = origin if origin is not None else os.environ.get('CATALOG_ORIGIN')
        app.state.catalog = None
        app.state.catalog_error = None
        try:
            app.state.catalog = load_catalog(path, origin=configured_origin)
        except CatalogError as exc:
            app.state.catalog_error = exc
            logger.error('Каталог не загружен:\n%s', exc)
        yield
        app.state.catalog = None

    app = FastAPI(title='AI-ANA: подбор подрядчиков', version='0.2.0', lifespan=lifespan)

    @app.exception_handler(QueryValidationError)
    async def query_error(_request: Request, exc: QueryValidationError):
        return error_response('INVALID_QUERY', 'Проверьте параметры мероприятия.', 422,
                              [asdict(issue) for issue in exc.issues])

    @app.exception_handler(RequestValidationError)
    async def body_error(_request: Request, exc: RequestValidationError):
        messages = {
            'missing': 'Заполните обязательное поле',
            'extra_forbidden': 'Неизвестное поле запроса',
            'int_type': 'Бюджет должен быть целым числом тенге',
            'greater_than': 'Число должно быть больше нуля',
            'less_than_equal': 'Бюджет превышает точный числовой диапазон браузера: 9 007 199 254 740 991 ₸',
            'string_type': 'Ожидается строка',
            'json_invalid': 'Некорректный JSON запроса',
            'model_attributes_type': 'Запрос должен быть объектом с параметрами мероприятия',
        }
        issues = []
        for error in exc.errors():
            # Never return rejected values, the raw body, tracebacks or exception context.
            field = '.'.join(str(v) for v in error['loc'] if v != 'body') or 'query'
            message = messages.get(error['type'], 'Некорректное значение поля')
            if error['type'] == 'value_error':
                message = error['msg'].removeprefix('Value error, ')
            issues.append({'field': clean_display(field)[:120], 'message': clean_display(message)})
        return error_response('INVALID_QUERY', 'Проверьте параметры мероприятия.', 422, issues)

    @app.exception_handler(Exception)
    async def internal_error(_request: Request, exc: Exception):
        logger.error('Ошибка обработки запроса: %s', type(exc).__name__)
        return error_response('INTERNAL_ERROR', 'Не удалось выполнить подбор. Повторите запрос позже.', 500)

    errors = {503: {'model': ErrorResponse}, 500: {'model': ErrorResponse}}

    @app.get('/health', response_model=HealthResponse, responses=errors)
    def health():
        catalog = app.state.catalog
        if catalog is None:
            return error_response('CATALOG_LOAD_FAILED', 'Каталог не загружен. Подробности в журнале сервера.', 503)
        return HealthResponse(status='ready', profile_count=len(catalog.profiles), catalog_version=catalog.version)

    @app.get('/api/catalog/meta', response_model=CatalogMetadata, responses=errors)
    def metadata():
        if app.state.catalog is None:
            return error_response('CATALOG_LOAD_FAILED', 'Каталог недоступен.', 503)
        return app.state.catalog.report()

    @app.post('/api/recommendations', response_model=RecommendationResponse,
              responses={**errors, 422: {'model': ErrorResponse}})
    def recommendations(query: RecommendationRequest):
        if app.state.catalog is None:
            return error_response('CATALOG_LOAD_FAILED', 'Каталог недоступен.', 503)
        result = recommend(query, app.state.catalog)
        return build_response(result, app.state.catalog)

    return app


app = create_app()
