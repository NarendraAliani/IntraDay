# LOCAL_DEVELOPMENT.md

Developer workflow commands for the tooling bootstrapped at Checkpoint 4.
For *why* each tool was chosen, see
[docs/architecture/TECHNOLOGY_MAPPING.md](../architecture/TECHNOLOGY_MAPPING.md)
— this document is commands only, not rationale.

## First-time setup

```bash
poetry install                  # installs backend deps (see pyproject.toml)
cp .env.example .env            # then fill in local values — never commit .env
cd frontend && npm install      # installs frontend deps (regenerable; not committed)
```

## Backend commands

| Command | What it does |
|---|---|
| `make install` / `poetry install` | Install/sync Python dependencies from `poetry.lock` |
| `make format` / `poetry run ruff format .` | Auto-format code |
| `make lint` / `poetry run ruff check .` | Lint (matches CI's `ruff check .`) |
| `make typecheck` / `poetry run mypy` | Strict type-check project code |
| `make test` / `poetry run pytest` | Run the test suite (unit + integration; integration tests skip gracefully without live Postgres/Redis) |
| `make architecture-check` / `poetry run lint-imports` | Enforce the approved dependency-direction rules (`.importlinter`) |
| `make check` | Runs format + lint + typecheck + architecture-check + test, in that order |
| `poetry run python manage.py check` | Django's own system check |
| `poetry run python manage.py migrate` | Apply migrations (none exist yet beyond Django's own built-in apps) |
| `poetry run python manage.py spectacular --file openapi.json` | Generate the current OpenAPI schema (infrastructure endpoints only, for now) |

Django management commands default to `intraday.settings.development`
(`manage.py`'s own default). Override explicitly for other environments:

```bash
DJANGO_SETTINGS_MODULE=intraday.settings.testing poetry run pytest
```

## Frontend commands

| Command | What it does |
|---|---|
| `npm run dev` | Start the Vite dev server |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run build` | Production build (`tsc -b && vite build`) |

## Docker (local development only — see `docker-compose.yml`)

| Command | What it does |
|---|---|
| `make dev-up` / `docker compose up -d` | Start Postgres, Redis, Django (`web`), Celery worker, Celery beat |
| `make dev-down` / `docker compose down` | Stop and remove containers |
| `make dev-logs` / `docker compose logs -f` | Tail logs from all services |

The compose file is hardcoded to `intraday.settings.development` — it
cannot be pointed at production or a live broker by accident (Checkpoint 4
§21). A separate production/paper deployment configuration is an
explicitly deferred Checkpoint 17 concern.

## Migrations

No domain models exist yet, so there is nothing to migrate beyond Django's
own built-in apps (`auth`, `admin`, `sessions`, `contenttypes`). Do **not**
create placeholder/fake migrations to exercise the tooling — `make check`
already proves `manage.py makemigrations --check --dry-run` reports "No
changes detected", which is the correct state at this checkpoint.

## CI

`.github/workflows/ci.yml` runs on every PR and on push to `main`: Ruff
format check, Ruff lint, mypy strict, pytest (with real Postgres/Redis
service containers), import-linter, Django migration check, secret scan
(gitleaks), dependency vulnerability audit (pip-audit), and an OpenAPI
schema-generation smoke check. No deployment step exists yet.
