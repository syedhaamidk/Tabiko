# Makes `tests` a package so pytest inserts `backend/` (not `tests/`) into
# sys.path. Without this, `from app import ...` only works when the CWD is
# already on the path — i.e. `python -m pytest` works but bare `pytest` (which
# is what CI runs) dies in conftest with `ModuleNotFoundError: No module named
# 'app'`. Do not delete this file.
