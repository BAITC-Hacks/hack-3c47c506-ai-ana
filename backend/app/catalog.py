"""CSV/JSONL adapters, provenance, validation report and deterministic import."""
from collections import Counter
import csv
from dataclasses import asdict, dataclass
from decimal import Decimal, DecimalException, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import ValidationError

from .models import CALENDAR_END, CALENDAR_START, Profile, decimal_text, normalize_key

Origin = Literal['original', 'team', 'demo']
ORIGINS = ('original', 'team', 'demo')
FIELDS = tuple(Profile.model_fields)
LISTS = ('categories', 'event_formats', 'languages', 'busy_dates')
FLAGS = ('synthetic', 'city_imputed', 'price_imputed')


@dataclass(frozen=True)
class Issue:
    source: str
    line: int | None
    profile_id: str | None
    field: str
    message: str


class CatalogError(ValueError):
    def __init__(self, issues: list[Issue] | tuple[Issue, ...]):
        self.issues = tuple(issues)
        super().__init__('\n'.join(
            f'{i.source}: строка {i.line or "—"}, id {i.profile_id or "—"}, '
            f'поле {i.field}: {i.message}' for i in self.issues
        ))


@dataclass(frozen=True)
class Provenance:
    profile_id: str
    source: str
    line: int
    source_sha256: str
    origin: Origin


@dataclass(frozen=True)
class Catalog:
    profiles: tuple[Profile, ...]
    version: str
    source_sha256: str
    source_path: str
    origin: Origin
    provenance: tuple[Provenance, ...]

    def report(self) -> dict[str, Any]:
        def labels(field: str) -> list[str]:
            values: dict[str, str] = {}
            for p in self.profiles:
                for value in (getattr(p, field) if field != 'city' else (p.city,)):
                    key = normalize_key(value)
                    values[key] = min(value, values.get(key, value))
            return [values[key] for key in sorted(values)]
        return {
            'status': 'ready', 'catalog_version': self.version,
            'source_sha256': self.source_sha256, 'origin': self.origin,
            'profile_count': len(self.profiles),
            'calendar': {'start': CALENDAR_START.isoformat(), 'end': CALENDAR_END.isoformat()},
            'dictionaries': {field: labels(field) for field in ('city', 'categories', 'event_formats', 'languages')},
            'quality': {
                'synthetic': sum(p.synthetic for p in self.profiles),
                'city_imputed': sum(p.city_imputed for p in self.profiles),
                'price_imputed': sum(p.price_imputed for p in self.profiles),
                'null_max_hours': sum(p.max_hours is None for p in self.profiles),
            },
            'city_counts': dict(sorted(Counter(p.city for p in self.profiles).items())),
            'category_counts': dict(sorted(Counter(c for p in self.profiles for c in p.categories).items())),
        }


def _issue(path: Path, line: int | None, field: str, message: str, ident: str | None = None) -> CatalogError:
    return CatalogError([Issue(str(path), line, ident, field, message)])


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Повторяющийся ключ JSON: {key}')
        result[key] = value
    return result


def _parse_json(text: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f'Недопустимое число JSON: {value}')
    try:
        result = json.loads(text, parse_float=Decimal, parse_constant=reject_constant, object_pairs_hook=_json_object)
    except DecimalException as exc:
        raise ValueError('Число JSON вне допустимого диапазона Decimal') from exc

    def check_unicode(value: Any) -> None:
        if isinstance(value, str):
            try:
                value.encode('utf-8')
            except UnicodeError as exc:
                raise ValueError('Строка JSON содержит некорректный Unicode') from exc
        elif isinstance(value, dict):
            for key, item in value.items():
                check_unicode(key)
                check_unicode(item)
        elif isinstance(value, list):
            for item in value:
                check_unicode(item)
    check_unicode(result)
    return result


def _csv_rows(text: str, path: Path):
    reader = csv.reader(io.StringIO(text, newline=''), strict=True)
    try:
        header = next(reader, [])
        missing, extra = set(FIELDS) - set(header), set(header) - set(FIELDS)
        issues = [Issue(str(path), 1, None, key, 'Отсутствует обязательный столбец') for key in sorted(missing)]
        issues += [Issue(str(path), 1, None, key, 'Неизвестный столбец') for key in sorted(extra)]
        if len(header) != len(set(header)):
            issues.append(Issue(str(path), 1, None, 'header', 'Повторяющиеся столбцы'))
        if issues:
            raise CatalogError(issues)
        while True:
            line = reader.line_num + 1
            row = next(reader, None)
            if row is None:
                return
            if len(row) != len(header):
                raise _issue(path, line, 'row', 'Число ячеек не совпадает с заголовком')
            data: dict[str, Any] = dict(zip(header, row))
            for key in LISTS:
                data[key] = [] if data[key] == '' else data[key].split('|')
            # Only the CSV adapter interprets strings as numbers/booleans.
            for key in FLAGS:
                if data[key] not in ('True', 'False'):
                    raise _issue(path, line, key, 'Ожидается True или False', data.get('id'))
                data[key] = data[key] == 'True'
            if not re.fullmatch(r'[0-9]+', data['price_from_kzt']):
                raise _issue(path, line, 'price_from_kzt', 'Ожидается целое число тенге', data.get('id'))
            try:
                data['price_from_kzt'] = int(data['price_from_kzt'])
                data['max_hours'] = None if data['max_hours'] == '' else Decimal(data['max_hours'])
            except (ValueError, InvalidOperation) as exc:
                raise _issue(path, line, 'max_hours', 'Ожидается число или пустая ячейка', data.get('id')) from exc
            yield line, data
    except csv.Error as exc:
        raise _issue(path, reader.line_num, 'csv', 'Повреждён CSV: ' + str(exc)) from exc


def _jsonl_rows(text: str, path: Path):
    lines = text.split('\n')
    if lines and lines[-1] == '':
        lines.pop()  # One final newline terminates the last record.
    for line, raw in enumerate(lines, 1):
        if not raw.strip():
            raise _issue(path, line, 'json', 'Пустая строка JSONL')
        try:
            data = _parse_json(raw)
        except (ValueError, RecursionError) as exc:
            raise _issue(path, line, 'json', 'Повреждён JSON: ' + str(exc)) from exc
        if not isinstance(data, dict):
            raise _issue(path, line, 'json', 'Запись должна быть JSON-объектом')
        yield line, data


def _profile_dict(profile: Profile, *, canonical: bool = False) -> dict[str, Any]:
    data = profile.model_dump(mode='python')
    for key in ('categories', 'event_formats', 'languages'):
        data[key] = sorted(data[key]) if canonical else list(data[key])
    data['busy_dates'] = [d.isoformat() for d in (sorted(profile.busy_dates) if canonical else profile.busy_dates)]
    return data


def _encode(value: Any) -> str:
    """JSON numbers for Decimal, without rounding through binary floats."""
    if isinstance(value, Decimal):
        # JSON number, with no quotes and no binary-float rounding.
        return decimal_text(value)
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(k, ensure_ascii=False) + ':' + _encode(v) for k, v in sorted(value.items())) + '}'
    if isinstance(value, (list, tuple)):
        return '[' + ','.join(_encode(v) for v in value) + ']'
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _manifest_path(path: Path) -> Path:
    return path.with_name(path.name + '.meta.json')


def load_catalog(path: Path, *, origin: Origin | None = None) -> Catalog:
    path = Path(path)
    if origin is not None and origin not in ORIGINS:
        raise _issue(path, None, 'origin', 'Происхождение должно быть original, team или demo')
    try:
        raw = path.read_bytes()
        text = raw.decode('utf-8-sig')
    except (OSError, UnicodeError) as exc:
        raise _issue(path, None, 'file', 'Не удалось прочитать файл UTF-8') from exc
    digest = hashlib.sha256(raw).hexdigest()
    manifest = None
    manifest_path = _manifest_path(path)
    if path.suffix.lower() == '.jsonl' and manifest_path.exists():
        try:
            manifest = _parse_json(manifest_path.read_text(encoding='utf-8'))
            if not isinstance(manifest, dict) or manifest.get('schema_version') != 1 or manifest.get('origin') not in ORIGINS:
                raise ValueError('Неверная схема метаданных')
            if manifest.get('export_sha256') != digest:
                raise ValueError('Отпечаток JSONL не совпадает с метаданными')
            if origin is not None and origin != manifest['origin']:
                raise ValueError('Запрошенное происхождение противоречит метаданным')
            origin = manifest['origin']
        except (OSError, ValueError, UnicodeError, RecursionError) as exc:
            raise _issue(manifest_path, None, 'metadata', 'Ошибка метаданных происхождения: ' + str(exc)) from exc
    origin = origin or 'original'
    if path.suffix.lower() not in ('.csv', '.jsonl'):
        raise _issue(path, None, 'file', 'Поддерживаются только CSV и JSONL')
    profiles, provenance, issues = [], [], []
    ids: set[str] = set()
    for line, data in (_csv_rows(text, path) if path.suffix.lower() == '.csv' else _jsonl_rows(text, path)):
        try:
            profile = Profile.model_validate(data)
        except ValidationError as exc:
            messages = {'missing': 'Отсутствует обязательное поле', 'extra_forbidden': 'Неизвестное поле',
                        'int_type': 'Ожидается целое число, не строка и не логическое значение',
                        'bool_type': 'Ожидается логическое значение true/false', 'string_type': 'Ожидается строка'}
            for error in exc.errors(include_input=False, include_url=False):
                message = messages.get(error['type'], error['msg'].removeprefix('Value error, '))
                issues.append(Issue(str(path), line, str(data.get('id', '')) or None,
                                    '.'.join(map(str, error['loc'])), message))
            continue
        key = normalize_key(profile.id)
        if key in ids:
            issues.append(Issue(str(path), line, profile.id, 'id', 'Повторяющийся идентификатор'))
        ids.add(key)
        if origin in ('demo', 'team') and not profile.synthetic:
            issues.append(Issue(str(path), line, profile.id, 'synthetic', 'Демо и добавленные командой записи должны быть синтетическими'))
        profiles.append(profile)
        provenance.append(Provenance(profile.id, str(path), line, digest, origin))
    if issues:
        raise CatalogError(issues)
    if not profiles:
        raise _issue(path, None, 'catalog', 'Каталог пуст: нет профилей')
    if manifest is not None:
        try:
            saved = [Provenance(**item) for item in manifest['records']]
            if len(saved) != len(profiles) or {p.profile_id for p in saved} != {p.id for p in profiles}:
                raise ValueError('Состав профилей не совпадает с метаданными')
            for item in saved:
                if item.origin != origin or type(item.line) is not int or item.line < 1 or not isinstance(item.source, str) or not re.fullmatch(r'[0-9a-f]{64}', item.source_sha256):
                    raise ValueError('Некорректное происхождение записи')
            provenance = saved
        except (KeyError, TypeError, ValueError) as exc:
            raise _issue(manifest_path, None, 'metadata', 'Некорректные метаданные записей') from exc
    ordered = tuple(sorted(profiles, key=lambda p: normalize_key(p.id)))
    canonical = _encode({'schema': 1, 'origin': origin, 'profiles': [_profile_dict(p, canonical=True) for p in ordered]})
    version = 'catalog-v1:' + hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    return Catalog(ordered, version, digest, str(path), origin, tuple(sorted(provenance, key=lambda p: normalize_key(p.profile_id))))


def export_jsonl(catalog: Catalog, path: Path) -> None:
    """Write a new derived file and provenance sidecar; never overwrite a source."""
    path = Path(path)
    if path.suffix.lower() != '.jsonl':
        raise _issue(path, None, 'file', 'Для экспорта нужно расширение .jsonl')
    manifest_path = _manifest_path(path)
    if path.exists() or manifest_path.exists():
        raise _issue(path, None, 'file', 'Экспорт не перезаписывает существующие файлы')
    raw = ('\n'.join(_encode(_profile_dict(p)) for p in catalog.profiles) + '\n').encode('utf-8')
    metadata = {'schema_version': 1, 'origin': catalog.origin,
                'export_sha256': hashlib.sha256(raw).hexdigest(),
                'records': [asdict(p) for p in catalog.provenance]}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw)
        with manifest_path.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    except OSError as exc:
        raise _issue(path, None, 'file', 'Не удалось сохранить экспорт и метаданные; проверьте оба файла') from exc
