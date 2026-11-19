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
