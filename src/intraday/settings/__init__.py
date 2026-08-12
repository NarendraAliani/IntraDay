# src/intraday/settings/__init__.py
#
# Django settings package (Checkpoint 4). Intentionally named `settings/`
# rather than `config/` to avoid colliding with the repository's approved
# top-level `config/` directory, which holds configuration *data*
# (config/broker, config/risk, config/strategies, config/universe,
# config/environments) per Checkpoints 1-3 — not Django project code. This
# is a deliberate naming choice to keep technology from distorting the
# approved architecture (Checkpoint 3 §3), documented here and in
# taskReport.md's Checkpoint 4 section.
#
# No settings module is imported by default here — the environment
# (DJANGO_SETTINGS_MODULE) always selects one of base/development/testing/
# paper/production explicitly. There is no default that could silently
# resolve to production.
