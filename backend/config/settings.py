import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "development-only-change-before-network-use")
DEBUG = os.environ.get("DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver,app").split(",")
CSRF_TRUSTED_ORIGINS = [x for x in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if x]
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_q",
    "accounting",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
if os.environ.get("POSTGRES_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "accountant"),
            "USER": os.getenv("POSTGRES_USER", "accountant"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
            "HOST": os.environ["POSTGRES_HOST"],
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 0,
        }
    }
else:
    # Explicitly a local development/test fallback, never the Compose database.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.getenv("SQLITE_PATH", str(BASE_DIR.parent / "var/dev.sqlite3")),
            "OPTIONS": {"timeout": 30},
        }
    }
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "de-at"
TIME_ZONE = "Europe/Vienna"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR.parent / "var/static"
DATA_ROOT = Path(os.getenv("DATA_ROOT", str(BASE_DIR.parent / "var/documents")))
SPA_ROOT = Path(os.getenv("SPA_ROOT", str(BASE_DIR.parent / "frontend/build/client")))
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SAMESITE = "Strict"
X_FRAME_OPTIONS = "SAMEORIGIN"
SECURE_CONTENT_TYPE_NOSNIFF = True
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", str(25 * 1024 * 1024)))
if not 0 < MAX_FILE_BYTES <= 25 * 1024 * 1024:
    raise ValueError("MAX_FILE_BYTES must be <= ClamAV/parser limit of 25 MiB")
CLAMAV_HOST = os.getenv("CLAMAV_HOST", "clamav")
CLAMAV_GATEWAY_PORT = int(os.getenv("CLAMAV_GATEWAY_PORT", "3311"))
CLAMAV_TIMEOUT = int(os.getenv("CLAMAV_TIMEOUT", "60"))
if not 1 <= CLAMAV_TIMEOUT <= 60:
    raise ValueError("CLAMAV_TIMEOUT must be between 1 and 60 seconds")
CLAMAV_MAX_ATTEMPTS = 3
CLAMAV_RETRY_SECONDS = 300
CLAMAV_LEASE_SECONDS = 300
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_FILE_BYTES + 2 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
MAX_MAIL_BYTES = 50 * 1024 * 1024
MAX_PACKAGE_BYTES = int(os.getenv("MAX_PACKAGE_BYTES", str(256 * 1024 * 1024)))
MAX_PACKAGE_SOURCE_FILES = int(os.getenv("MAX_PACKAGE_SOURCE_FILES", "10000"))
MAX_WORKBOOK_BANK_ROWS = int(os.getenv("MAX_WORKBOOK_BANK_ROWS", "10000"))
MAX_WORKBOOK_BANK_BYTES = int(os.getenv("MAX_WORKBOOK_BANK_BYTES", str(16 * 1024 * 1024)))
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounting.auth.BearerAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "EXCEPTION_HANDLER": "accounting.api.exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "30/min"},
}
# Q2 status uses a process-shared framework cache within the worker container;
# jobs themselves always use the PostgreSQL ORM broker, not this cache.
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "qstats": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": "/tmp/lazy-accountant-qstats",
    },
}
Q_CLUSTER = {
    "name": "accountant",
    "orm": "default",
    "cache": "qstats",
    "workers": 2,
    "timeout": 300,
    "retry": 420,
    "queue_limit": 20,
    "bulk": 1,
    "max_attempts": 1,
    "ack_failures": True,
    "recycle": 100,
    "sync": os.getenv("Q_SYNC", "0") == "1",
}
MAILERS = {
    "default": {
        "BACKEND": os.getenv("MAIL_BACKEND", "accounting.smtp.EmailBackend"),
        "OPTIONS": {"host": "localhost"},
    }
}
MCP_ALLOWED_HOSTS = os.getenv("MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,app:8000").split(",")
MCP_ALLOWED_ORIGINS = os.getenv(
    "MCP_ALLOWED_ORIGINS", "http://localhost:*,http://127.0.0.1:*,http://app:8000"
).split(",")
