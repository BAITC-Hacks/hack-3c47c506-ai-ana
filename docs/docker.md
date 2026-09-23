# Docker: сайт и API

Compose собирает два образа из исходников. `backend` содержит Python 3.13, FastAPI, полный исходный CSV и факты для объяснений. `frontend` собирает React с Node 22 и отдаёт статические файлы через Nginx. Vite dev-сервер в контейнере не используется.

## Запуск

Нужны Docker Engine с Compose либо Docker Desktop. Все команды — из корня репозитория. Первый запуск загружает базовые образы и зависимости из сети.

```bash
docker compose config --quiet
docker compose up --build -d --wait
docker compose ps
```

Откройте http://localhost:8080. API-документация: http://localhost:8080/docs. Проверка готовности API: http://localhost:8080/health; ожидается `ready` и 66 профилей. `/healthz` проверяет отдельно Nginx. В `compose ps` оба сервиса должны иметь состояние healthy.

По умолчанию порт 8080 опубликован только на `127.0.0.1`, backend наружу не опубликован. Nginx передаёт `/api`, `/health`, `/docs`, `/redoc` и `/openapi.json` серверу. Cookie аккаунта работает через тот же адрес сайта; отдельная настройка CORS не нужна. При пересоздании backend Nginx обновляет его адрес через DNS Docker.

Оба контейнера работают от непривилегированного пользователя с файловой системой только для чтения. Временные файлы размещаются в `/tmp`, база — в отдельном volume. Каталог и разметка входят в образ и не изменяются при работе.

## Настройки

Для других значений создайте корневой `.env` по `.env.example` (не заменяйте существующий файл со своими настройками):

```dotenv
APP_PORT=8080
AUTH_COOKIE_SECURE=false
# AUTH_ALLOWED_ORIGINS=https://your-domain.example
```

Compose читает этот файл и передаёт только указанные в конфигурации настройки. `backend/.env.example` относится к запуску Python без Docker. Без явного `AUTH_ALLOWED_ORIGINS` разрешены `http://localhost:APP_PORT` и `http://127.0.0.1:APP_PORT`. После изменения настроек выполните `docker compose up -d --wait`.

Для сайта за HTTPS задайте `AUTH_COOKIE_SECURE=true`, точный внешний origin и настройте TLS на внешнем reverse proxy, доступном по тому же loopback-порту. Текущая конфигурация не выпускает сертификаты и не публикует сайт в интернет.

## Данные аккаунтов

SQLite хранится в именованном volume `auth-data`, по умолчанию Docker называет его `ai-ana_auth-data`. Он сохраняется при `docker compose down`, пересоздании контейнеров и новой сборке. Команда `docker compose down --volumes` удаляет базу; для обычной остановки используйте команду без этого флага.

На новом компьютере volume и пустая SQLite со всеми таблицами создаются автоматически. Пользователи разных компьютеров регистрируются независимо: базы не передаются через Git и не синхронизируются. Начальные аккаунты и общий пароль отсутствуют.

Если нужны две независимые копии на **одном компьютере**, задайте второй копии другое имя проекта и порт в её корневом `.env`:

```dotenv
COMPOSE_PROJECT_NAME=ai-ana-second
APP_PORT=8081
```

У второй копии появится отдельный volume `ai-ana-second_auth-data`. При обычной работе сохраняйте выбранное имя проекта, иначе Compose подключит другой volume. После переноса папки на тот же компьютер под тем же именем проекта прежняя база продолжит использоваться.

База с хоста `data/auth/accounts.sqlite3` не копируется в образ: новый Docker volume начинает с пустого списка аккаунтов. Исходный локальный файл остаётся на месте. Для переноса уже созданных локальных аккаунтов используйте SQLite backup API, чтобы включить изменения из WAL. Пример ниже **предназначен для нового пустого Docker volume до первого запуска API**; импорт откажется заменять существующую базу.

1. Соберите образы: `docker compose build`.
2. Остановите изменения аккаунтов в прежнем локальном приложении на время переноса.
3. Создайте локальный согласованный backup (нужен Python только для этой операции):

```bash
python3 - <<'PY'
from pathlib import Path
import os
import sqlite3

source = Path('data/auth/accounts.sqlite3')
backup = Path('data/auth/docker-migration.sqlite3')
if not source.is_file():
    raise SystemExit('Локальная база отсутствует')
fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
os.close(fd)
with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as src:
    with sqlite3.connect(backup) as dest:
        src.backup(dest)
print('Создан', backup)
PY
```

4. Импортируйте backup в новый volume от имени пользователя backend:

```bash
docker compose run --rm -T --no-deps backend python -c 'import os,sys; p="/app/data/auth/accounts.sqlite3"; fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); f=os.fdopen(fd,"wb"); f.write(sys.stdin.buffer.read()); f.close()' < data/auth/docker-migration.sqlite3
docker compose up -d --wait
```

Перенос сохраняет аккаунты и сессии. При работе через новый порт браузер может использовать прежнюю cookie для того же hostname — cookie не привязана к порту. Две базы после переноса независимы; не используйте старый и новый серверы для параллельного редактирования одного аккаунта.

## Проверки и обслуживание

```bash
docker compose logs --tail=100 backend frontend
docker compose restart
docker compose up --build -d --wait
docker compose down
```

После запуска проверьте подбор, регистрацию, сохранение имени/города, выход и повторный вход. После `docker compose restart` аккаунт должен оставаться доступным. Для проверки повторной сборки создавайте тестовый аккаунт только с вымышленным email и отдельным паролем.

Секреты, `.git`, локальные аккаунты, `.venv`, `node_modules` и результаты браузерных тестов исключены из build context. Пароли аккаунтов и токены не должны попадать в Git или образы. Сборка использует закреплённые зависимости приложения; базовые образы закреплены по линии Python/Node, их patch-версии могут обновляться.

## Статус проверки

Проверено 23.09.2026 на Docker Engine 26.1.5 и Compose 2.26.1:

- Образы backend и frontend собраны; оба сервиса healthy.
- Через Nginx прошли загрузка сайта, каталог, подбор, регистрация, изменение профиля и выход.
- В отдельном проекте `ai-ana-check` на порту 8081 создан тестовый аккаунт. После `down` без удаления volume и нового `up` вход в этот аккаунт и сохранённые имя/город работают.
- Основной проект `ai-ana` на порту 8080 получил отдельную пустую базу: 0 пользователей; тестовый аккаунт туда не попал.
- В чистую временную копию исходников из Git база не переносилась. При первом запуске она создалась пустой; регистрация и профиль сохранились после повторного запуска API.
- Проверена конфигурация второй копии через `COMPOSE_PROJECT_NAME` и `APP_PORT`.

Для проверки чистой копии Python использовалось уже установленное окружение зависимостей; Docker-образы собраны через отдельную установку зависимостей внутри образов.

Справка: [Compose и интерполяция переменных](https://docs.docker.com/reference/compose-file/interpolation/), [volumes в Docker](https://docs.docker.com/engine/storage/volumes/).
