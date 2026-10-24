"""Shared test setup. Existing API tests run as a signed-in admin; tests/test_security.py exercises real sign-in."""
import os

os.environ.setdefault('ALLOWED_HOSTS', 'testserver,localhost,127.0.0.1')
os.environ.setdefault('WATCH_SCHEDULER', '0')  # no background collection in tests
os.environ.setdefault('WATCH_SAVE_PICTURES', '0')
os.environ.setdefault('WATCH_PREVIEWS', '0')     # no article fetches for news results
os.environ.setdefault('WATCH_SCREENSHOTS', '0')  # no picture downloads after test runs
import tempfile
os.environ.setdefault('WATCH_PICTURES_DIR', tempfile.mkdtemp(prefix='pictures-'))

import pytest

from api.main import app
from api.security import AuthUser, limiter, require_user, current_user

TEST_USER = AuthUser(id=1, username='tester', role='admin', csrf='test-csrf')


@pytest.fixture(autouse=True)
def signed_in_user(request):
    limiter.clear()
    if request.node.get_closest_marker('real_auth') is None:
        app.dependency_overrides[current_user] = lambda: TEST_USER
        app.dependency_overrides[require_user] = lambda: TEST_USER
    yield
    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(require_user, None)
    limiter.clear()


def pytest_configure(config):
    config.addinivalue_line('markers', 'real_auth: use the real session and CSRF checks')
