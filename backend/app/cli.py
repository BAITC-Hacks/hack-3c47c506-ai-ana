"""Reproducible local audit and CSV-to-JSONL export."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .catalog import CatalogError, export_jsonl, load_catalog
from .main import DEFAULT_CATALOG, PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description='Проверить каталог AI-ANA и при необходимости экспортировать JSONL')
    parser.add_argument('path', nargs='?', type=Path, default=DEFAULT_CATALOG)
    parser.add_argument('--origin', choices=('original', 'team', 'demo'))
    parser.add_argument('--export', type=Path, help='Новый JSONL и файл .meta.json; существующие файлы не перезаписываются')
    args = parser.parse_args()
    source = args.path if args.path.is_absolute() else PROJECT_ROOT / args.path
    target = (args.export if args.export.is_absolute() else PROJECT_ROOT / args.export) if args.export else None
    try:
        catalog = load_catalog(source, origin=args.origin)
        if target:
            export_jsonl(catalog, target)
        report = catalog.report()
        report['source_path'] = str(source)
        report['provenance'] = [asdict(item) for item in catalog.provenance]
        if target:
            report['export_path'] = str(target)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except CatalogError as exc:
        print(json.dumps({'status': 'error', 'issues': [asdict(i) for i in exc.issues]}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
