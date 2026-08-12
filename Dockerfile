# Dockerfile
#
# Repository root. Development-oriented image for the Django/Celery/
# Channels application (Checkpoint 4 — infrastructure bootstrap only, no
# business logic). A separate, hardened production image is an explicitly
# deferred Checkpoint 17 concern (see
# docs/architecture/TECHNOLOGY_MAPPING.md §14).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_VERSION=2.4.1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "poetry==${POETRY_VERSION}"

# Dependencies installed in their own layer so source changes don't bust
# the dependency-install cache.
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --no-interaction --no-ansi

COPY src ./src
COPY manage.py ./manage.py
RUN poetry install --no-interaction --no-ansi

EXPOSE 8000

# ASGI (Daphne) is the real serving entrypoint — see intraday/asgi.py and
# TECHNOLOGY_MAPPING.md §2 (Channels serves REST + WebSocket in one
# deployable). This default CMD is overridden by docker-compose.yml for the
# celery_worker/celery_beat services.
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "intraday.asgi:application"]
