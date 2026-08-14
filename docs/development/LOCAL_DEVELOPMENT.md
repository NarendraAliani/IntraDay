# LOCAL_DEVELOPMENT.md

Developer workflow commands for the tooling bootstrapped at Checkpoint 4.
For *why* each tool was chosen, see
[docs/architecture/TECHNOLOGY_MAPPING.md](../architecture/TECHNOLOGY_MAPPING.md)
— this document is commands only, not rationale.

> **Not a developer?** For a non-technical, interactive walkthrough of
> installing and running the app (including the single-click `app.bat`
> launcher), see
> [docs/user-guide/index.html](../user-guide/index.html) instead — this
> document assumes command-line familiarity and covers the full
> developer toolchain (linting, type-checking, tests, Docker), not just
> "get the app running."

## First-time setup

```bash
poetry install                  # installs backend deps (see pyproject.toml)
cp .env.example .env            # then fill in local values — never commit .env
cd frontend && npm install      # installs frontend deps (regenerable; not committed)
```

`.env` is loaded automatically by every `manage.py` command (Checkpoint
17.1: `settings/base.py` calls `load_dotenv()` — a real process/OS
environment variable always overrides a `.env` value, `.env` only fills
gaps). Previously `.env` was silently never read outside `docker
compose` (whose own `env_file:` directive is unrelated to
`python-dotenv`) — this is now fixed; no separate manual export step is
required.

## Running PostgreSQL and Redis without Docker (Checkpoint 17.1)

If Docker is unavailable, PostgreSQL and Redis can run as native Windows
services/binaries instead — the same `POSTGRES_*`/`REDIS_URL` variables
in `.env` apply either way, since `settings/base.py` only ever reads
environment variables, never a Docker-specific mechanism.

- **PostgreSQL**: install (e.g. `winget install -e --id
  PostgreSQL.PostgreSQL.16`), then create the database/role matching
  your `.env` values:
  ```sql
  CREATE USER intraday WITH PASSWORD 'changeme';
  CREATE DATABASE intraday OWNER intraday;
  GRANT ALL PRIVILEGES ON DATABASE intraday TO intraday;
  ALTER USER intraday CREATEDB;  -- required so pytest-django can create/drop the test database
  ```
  Then `poetry run python manage.py migrate`.
- **Redis**: install as a native service (e.g. the official Windows
  build) or run any reachable Redis instance; `.env`'s `REDIS_URL`
  (default `redis://localhost:6379/0`) must point at it.

`poetry run python manage.py check` and `GET /readyz` (once the server
is running) both report `database`/`cache` connectivity honestly — use
`/readyz` to confirm both are actually reachable before assuming the
full authenticated workflow will work.

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

Beyond Django's own built-in apps (`auth`, `admin`, `sessions`,
`contenttypes`), `intraday.infrastructure.persistence` (Checkpoint 7+)
holds the configuration-versioning and audit-trail models — see
[docs/architecture/PERSISTENCE_ARCHITECTURE.md](../architecture/PERSISTENCE_ARCHITECTURE.md).
Run `poetry run python manage.py migrate` once PostgreSQL is reachable.
`manage.py makemigrations --check --dry-run` reporting "No changes
detected" remains the expected, correct state — do not create
placeholder/fake migrations to exercise the tooling.

## Development login user

No development/test user is seeded by any migration or fixture (only
the empty `configuration-operators` Group is seeded —
`0002_seed_configuration_operators_group.py`). Create one locally once
PostgreSQL is reachable:

```bash
poetry run python manage.py createsuperuser   # interactive; or see below for a scripted local-only user
```

To add an existing user to the operator role (grants the
`configuration.activate` capability):

```python
# poetry run python manage.py shell
from django.contrib.auth.models import User, Group
user = User.objects.get(username="your-username")
user.groups.add(Group.objects.get(name="configuration-operators"))
```

Never commit a generated password anywhere in this repository — it
exists only in your local PostgreSQL instance.

## Test isolation notes

`tests/conftest.py` (Checkpoint 17.2) clears Django's cache before and
after every test automatically. This matters if you add a test touching
anything cache-backed (rate-limit throttling, `CACHES["default"]`) —
without it, `LocMemCache`'s in-process state persists across tests
within a single `pytest` run (e.g. the login view's `5/min` throttle),
which previously caused unrelated, order-dependent test failures. You
should not need to do anything extra; this is automatic (`autouse=True`).

## CI

`.github/workflows/ci.yml` runs on every PR and on push to `main`: Ruff
format check, Ruff lint, mypy strict, pytest (with real Postgres/Redis
service containers), import-linter, Django migration check, secret scan
(gitleaks), dependency vulnerability audit (pip-audit), and an OpenAPI
schema-generation smoke check. No deployment step exists yet.
