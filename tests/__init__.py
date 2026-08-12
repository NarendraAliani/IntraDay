# tests/__init__.py
#
# Package marker so pytest resolves test modules by fully-qualified name,
# avoiding basename collisions across test subdirectories (e.g. two
# unrelated test_risk.py files). Added at Checkpoint 6 when the config
# schema tests introduced this project's first such collision.
