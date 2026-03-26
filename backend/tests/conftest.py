"""
Shared pytest configuration for the backend test suite.
"""
import pytest


@pytest.fixture(autouse=True)
def _disable_widget_origin_check(monkeypatch):
    """
    Patch WIDGET_SITE_KEYS to [] on the app module for every test.

    Without this, any test that posts to /chat without a JWT would be
    rejected with 401 "Unauthorized widget origin" whenever the real
    .env has WIDGET_SITE_KEYS configured.  Tests that explicitly need
    the site-key gate to be active can re-apply their own monkeypatch.
    """
    try:
        import app as app_module
        monkeypatch.setattr(app_module, "WIDGET_SITE_KEYS", [])
        # Prevent stale local-DB import hashes from triggering 409 on re-runs
        monkeypatch.setattr(app_module, "is_duplicate_import", lambda _hash: False)
    except Exception:  # noqa: BLE001
        # If `app` hasn't been imported yet or isn't available, skip silently.
        pass
