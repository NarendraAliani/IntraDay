# Makefile
#
# Repository root. Minimal developer command interface (Checkpoint 4 §23).
# Poetry itself already provides a scriptable interface (`poetry run ...`);
# this Makefile is a thin, boring convenience wrapper around it — not a
# second build system. See docs/development/LOCAL_DEVELOPMENT.md for the
# full command reference.

.PHONY: install format lint typecheck test architecture-check check migrate dev-up dev-down dev-logs

install:
	poetry install

format:
	poetry run ruff format .

lint:
	poetry run ruff check .

typecheck:
	poetry run mypy

test:
	poetry run pytest

architecture-check:
	poetry run lint-imports

check: format lint typecheck architecture-check test

migrate:
	poetry run python manage.py migrate

dev-up:
	docker compose up -d

dev-down:
	docker compose down

dev-logs:
	docker compose logs -f
