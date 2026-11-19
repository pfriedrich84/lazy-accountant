import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from accounting.auth import Actor
from accounting.demo import seed_companies


@pytest.fixture(autouse=True)
def data_root(settings, tmp_path):
    settings.DATA_ROOT = tmp_path / "documents"
    settings.Q_CLUSTER = {**settings.Q_CLUSTER, "sync": True}
    settings.MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}


@pytest.fixture(autouse=True)
def clean_scanner(request, monkeypatch):
    """Business regression tests use successful scans, never a production bypass.

    Security tests opt out and exercise the actual deferred state machine.
    """
    if request.node.get_closest_marker("security") or request.node.get_closest_marker("clamav"):
        return
    from django.db import transaction
    from accounting import scanner, security

    original = transaction.on_commit

    def commit(callback, using=None, robust=False):
        if callback.__module__ in {"accounting.services", "accounting.security"}:
            callback()
        else:
            original(callback, using=using, robust=robust)

    monkeypatch.setattr(transaction, "on_commit", commit)
    monkeypatch.setattr(security, "publish", security.run_scan)
    monkeypatch.setattr(scanner, "scan", lambda data: scanner.Verdict("clean", "test-engine/1"))


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user("test", password="test-password-12345")


@pytest.fixture
def actor(user):
    return Actor(user.id)


@pytest.fixture
def companies(user):
    return seed_companies(user)


@pytest.fixture
def client(user):
    client = APIClient()
    client.force_login(user)
    return client
