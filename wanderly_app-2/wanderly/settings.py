"""
Django settings for the Wanderly project.

Wanderly is a freshness-aware travel recommender built on three honest,
separable layers:

1. A data layer (`destinations`) holding normalized, provenance-stamped,
   time-grained facts about places (weather, cost, safety).
2. A deterministic intelligence layer (`intelligence`) that ranks
   destinations with per-factor, fully explainable scoring.
3. A presentation layer (an optional LLM `Explainer`) that turns scores
   into prose -- and is NEVER allowed to influence the ranking itself.

Security-sensitive values (SECRET_KEY, DEBUG, ALLOWED_HOSTS, database
credentials) are read from the environment so the same code runs safely
in local dev, CI, and production. Sensible local-dev defaults are
provided so a fresh checkout runs with zero configuration.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean from the environment ('1', 'true', 'yes' -> True)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# --- Core security -----------------------------------------------------------

# In production, SECRET_KEY MUST be supplied via the environment. The
# insecure fallback exists only so local development works out of the box.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-local-dev-only-CHANGE-ME-in-production",
)

DEBUG = _env_bool("DJANGO_DEBUG", default=True)

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

# CSRF trusted origins (needed once served behind a domain / HTTPS proxy).
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]


# --- Applications ------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts.apps.AccountsConfig",
    # Wanderly apps -- ordered by dependency (data first, intelligence next).
    "destinations.apps.DestinationsConfig",
    "intelligence.apps.IntelligenceConfig",
    "web.apps.WebConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves static files efficiently under gunicorn in prod.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "wanderly.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "wanderly.wsgi.application"
ASGI_APPLICATION = "wanderly.asgi.application"


# --- Database ----------------------------------------------------------------
#
# Default: SQLite, so a fresh clone runs immediately with no setup.
# Production: set DATABASE_URL-style env vars below to switch to PostgreSQL.
#
# Migration path SQLite -> PostgreSQL:
#   1. Provision Postgres and set DJANGO_DB_ENGINE=postgresql plus the
#      DJANGO_DB_* vars (or a single DATABASE_URL if you later add
#      dj-database-url).
#   2. `python manage.py migrate` against the empty Postgres database.
#   3. `python manage.py dumpdata --natural-foreign --natural-primary
#      destinations intelligence > seed.json` from SQLite, then
#      `loaddata seed.json` against Postgres -- or simply re-run the
#      `seed_demo` management command, which is environment-agnostic.

_DB_ENGINE = os.environ.get("DJANGO_DB_ENGINE", "sqlite3")

if _DB_ENGINE == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DJANGO_DB_NAME", "wanderly"),
            "USER": os.environ.get("DJANGO_DB_USER", "wanderly"),
            "PASSWORD": os.environ.get("DJANGO_DB_PASSWORD", ""),
            "HOST": os.environ.get("DJANGO_DB_HOST", "localhost"),
            "PORT": os.environ.get("DJANGO_DB_PORT", "5432"),
            # Reuse connections for up to 60s -- a cheap perf win under load.
            "CONN_MAX_AGE": int(os.environ.get("DJANGO_DB_CONN_MAX_AGE", "60")),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# --- Password validation -----------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# --- Internationalization ----------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# --- Static files ------------------------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
# Collected target for production (`collectstatic`); harmless in dev.
STATIC_ROOT = BASE_DIR / "staticfiles"

# Compressed, hashed static files served by WhiteNoise in production.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# Dev: print emails to console
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "Wanderly <noreply@wanderly.app>"

# Production SMTP (set via environment):
EMAIL_BACKEND    = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST       = os.environ.get("EMAIL_HOST")
EMAIL_PORT       = int(os.environ.get("EMAIL_PORT", 587))
EMAIL_USE_TLS    = True
EMAIL_HOST_USER  = os.environ.get("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL  = "Wanderly <noreply@wanderly.app>"

# --- Production hardening (only switched on when DEBUG is False) -------------
#
# These are no-ops in local dev but ensure we don't ship an insecure
# deployment. They satisfy `manage.py check --deploy`.

if not DEBUG:
    SECURE_SSL_REDIRECT = _env_bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # Trust the X-Forwarded-Proto header from a TLS-terminating proxy.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")



# --- Wanderly: LLM Explainer configuration -----------------------------------
#
# The Explainer is a presentation-only layer. The default is the
# NullExplainer, which uses the deterministic engine's own factor
# breakdown to produce a plain-language summary with NO external API call.
# Swapping to a real vendor (Gemini, Groq, ...) is a config change here,
# never an architecture change.

WANDERLY_EXPLAINER_BACKEND = os.environ.get(
    "WANDERLY_EXPLAINER_BACKEND", "intelligence.explainers.NullExplainer"
)
