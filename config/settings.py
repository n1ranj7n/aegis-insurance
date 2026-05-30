"""
Django settings for the Aegis Health Insurance demo platform.

Configuration is environment-driven so the same codebase runs locally and on a
PaaS (Render / Railway) without edits. See ``.env.example`` for every variable.
"""

from pathlib import Path

import dj_database_url
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# Load variables from a local .env file if present. In production the platform
# injects real environment variables, so a missing .env is fine.
load_dotenv(BASE_DIR / ".env")


# --------------------------------------------------------------------------- #
# Small env helpers
# --------------------------------------------------------------------------- #
def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Core security settings
# --------------------------------------------------------------------------- #
# A throwaway key is provided so the project boots out of the box for local dev.
# Production MUST set SECRET_KEY in the environment.
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-dev-only-key-CHANGE-ME-r_3gp7gmxpj2!1!544(8mq1$4g8wp8659",
)

DEBUG = env_bool("DEBUG", default=False)

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", default="localhost,127.0.0.1")

# Render/Railway expose the external hostname at runtime; trust it automatically.
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# CSRF trusted origins must be full scheme://host. Derive from ALLOWED_HOSTS plus
# any explicit overrides so POSTs from the deployed domain are accepted.
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
for host in ALLOWED_HOSTS:
    if host not in {"localhost", "127.0.0.1"}:
        CSRF_TRUSTED_ORIGINS.append(f"https://{host}")


# --------------------------------------------------------------------------- #
# Applications & middleware
# --------------------------------------------------------------------------- #
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "insurance",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves static files in production; must sit right after security.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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
                "insurance.context_processors.demo_banner",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# --------------------------------------------------------------------------- #
# Database (PostgreSQL via DATABASE_URL — e.g. a Neon connection string)
# --------------------------------------------------------------------------- #
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=env_int("DB_CONN_MAX_AGE", 600),
            # Neon requires SSL; honoured by the sslmode in the URL but kept here
            # as a safe default for plain connection strings.
            ssl_require=env_bool("DB_SSL_REQUIRE", default=True),
        )
    }
else:
    # Fallback so `manage.py` commands (e.g. collectstatic) work without a DB URL.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# --------------------------------------------------------------------------- #
# Caching (used by django-ratelimit to track POSTs per IP)
# --------------------------------------------------------------------------- #
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "aegis-ratelimit",
    }
}


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"


# --------------------------------------------------------------------------- #
# Internationalization (Indian health-insurance context)
# --------------------------------------------------------------------------- #
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True


# --------------------------------------------------------------------------- #
# Static files (WhiteNoise)
# --------------------------------------------------------------------------- #
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --------------------------------------------------------------------------- #
# Production hardening (only when DEBUG is off)
# --------------------------------------------------------------------------- #
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 3600)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True


# --------------------------------------------------------------------------- #
# Demo-safety knobs (see ARCHITECTURE.md → "Demo-safety design")
# --------------------------------------------------------------------------- #
# Max rows allowed per domain table before writes are refused.
DEMO_ROW_LIMIT = env_int("DEMO_ROW_LIMIT", 200)

# Per-IP POST budget enforced on write views by django-ratelimit.
DEMO_WRITE_RATE = os.environ.get("DEMO_WRITE_RATE", "30/m")

# Demo credentials seeded by `seed_demo` / `reset_demo` and shown on the login page.
DEMO_USERNAME = os.environ.get("DEMO_USERNAME", "demo")
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "demo1234")

# Banner copy shown site-wide.
DEMO_BANNER_TEXT = os.environ.get(
    "DEMO_BANNER_TEXT", "Demo environment — data resets daily."
)
