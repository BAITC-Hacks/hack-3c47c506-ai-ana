"""Local, reviewable matching diagnostics before the recommendation API exists."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .catalog import CatalogError, _parse_json, load_catalog
from .main import DEFAULT_CATALOG, PROJECT_ROOT
from .matching import recommend
from .matching_models import QueryIssue, QueryValidationError


def main() -> int:
    parser = argparse.ArgumentParser(description='Подбор из каталога без API: входной JSON и диагностика фильтров')
    parser.add_argument('--query', type=Path, required=True, help='JSON с параметрами запроса; относительный путь от корня проекта')
    parser.add_argument('--catalog', type=Path, default=DEFAULT_CATALOG)
    parser.add_argument('--origin', choices=('original', 'team', 'demo'))
    args = parser.parse_args()
    query_path = args.query if args.query.is_absolute() else PROJECT_ROOT / args.query
    catalog_path = args.catalog if args.catalog.is_absolute() else PROJECT_ROOT / args.catalog
    try:
        try:
            query = _parse_json(query_path.read_text(encoding='utf-8-sig'))
        except (OSError, UnicodeError, ValueError, RecursionError) as exc:
            raise QueryValidationError([QueryIssue('query_file', 'Не удалось прочитать корректный JSON запроса')]) from exc
        catalog = load_catalog(catalog_path, origin=args.origin)
        result = recommend(query, catalog)
        print(json.dumps(result.model_dump(mode='json'), ensure_ascii=False, indent=2))
        return 0
    except (CatalogError, QueryValidationError) as exc:
        code = 'CATALOG_LOAD_FAILED' if isinstance(exc, CatalogError) else 'INVALID_QUERY'
        print(json.dumps({'status': 'error', 'code': code, 'issues': [asdict(i) for i in exc.issues]}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
