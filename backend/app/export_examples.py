"""Save real public response examples for reviewers, without modifying source data."""
from datetime import date, timedelta
import json

from .catalog import load_catalog
from .explanations import build_response
from .main import DEFAULT_CATALOG, PROJECT_ROOT
from .matching import recommend


def main() -> None:
    catalog = load_catalog(DEFAULT_CATALOG)
    directory = PROJECT_ROOT / 'docs' / 'api-examples'
    directory.mkdir(exist_ok=True)
    for source in sorted((PROJECT_ROOT / 'docs' / 'queries').glob('*.json')):
        query = json.loads(source.read_text())
        result = build_response(recommend(query, catalog), catalog)
        (directory / source.name).write_text(json.dumps(result.model_dump(mode='json'), ensure_ascii=False, indent=2) + '\n')
    # A real source profile with a minimum that is absent from the structural schema.
    profile = next(p for p in catalog.profiles if p.id == 'HK-90009')
    day = next(date(2026, 9, 23) + timedelta(days=i) for i in range(100)
               if date(2026, 9, 23) + timedelta(days=i) not in profile.busy_dates)
    query = {'city': profile.city, 'category': 'Фото и видеобудки', 'event_format': 'корпоратив',
             'event_date': day.isoformat(), 'budget_kzt': 1_000_000, 'duration_hours': 2}
    result = build_response(recommend(query, catalog), catalog)
    (directory / 'minimum-duration.json').write_text(json.dumps(result.model_dump(mode='json'), ensure_ascii=False, indent=2) + '\n')
    print('Сохранены примеры публичных ответов в docs/api-examples/')


if __name__ == '__main__':
    main()
