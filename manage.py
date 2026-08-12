#!/usr/bin/env python
# manage.py
#
# Repository root. Standard Django management-command entrypoint
# (Checkpoint 4). Defaults DJANGO_SETTINGS_MODULE to the development
# settings module for local convenience only — every other environment
# (testing/paper/production) must set DJANGO_SETTINGS_MODULE explicitly;
# there is no default that could silently resolve to production.
from __future__ import annotations

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "intraday.settings.development")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Is it installed and available on your "
            "PYTHONPATH environment variable? Did you forget to activate a "
            "virtual environment? Run `poetry install` first."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
