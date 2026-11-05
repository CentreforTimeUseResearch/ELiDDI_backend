import os

import pytest


# The container sets ELIDDI_* variables for local use (compose.yaml). Tests
# must not depend on them, so each one starts without them.
@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in [name for name in os.environ if name.startswith('ELIDDI_')]:
        monkeypatch.delenv(name)
    # most tests run as a page from anywhere would; test_cors.py sets its own
    monkeypatch.setenv('ELIDDI_CORS_ORIGINS', '*')
