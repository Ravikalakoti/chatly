"""
Django settings for the chat project.

Everything that changes between your laptop and production is read from
environment variables, so the same code runs locally and on Render.
"""
import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def env_list(name):
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


# Render sets RENDER=true on its servers. Locally DEBUG defaults to True,
# on Render it defaults to False.
IS_RENDER = bool(os.environ.get("RENDER"))
DEBUG = env_bool("DEBUG", default=not IS_RENDER)

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-change-me"
    else:
        raise ImproperlyConfigured("The SECRET_KEY environment variable is required in production.")

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"] + env_list("ALLOWED_HOSTS")
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
if RENDER_EXTERNAL_URL:
    CSRF_TRUSTED_ORIGINS.append(RENDER_EXTERNAL_URL)

INSTALLED_APPS = [
    "daphne",  # must be first: makes `runserver` speak ASGI/websockets
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "accounts",
    "chat",
    "billing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --- Database ---------------------------------------------------------------
# SQLite locally; on Render DATABASE_URL points at Postgres.
DATABASES = {
    "default": dj_database_url.parse(
        os.environ.get("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

# --- Channels (real-time) ---------------------------------------------------
# The in-memory layer works for a single server process (perfect for a free
# Render instance). Set REDIS_URL to scale to several instances.
REDIS_URL = os.environ.get("REDIS_URL")
if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# --- Auth -------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "accounts.backends.IdentifierBackend",  # log in with phone or email
    "django.contrib.auth.backends.ModelBackend",  # keeps /admin username login working
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"  # the public landing page

# Phone numbers typed without a country code get this one (India = 91).
DEFAULT_COUNTRY_CODE = os.environ.get("DEFAULT_COUNTRY_CODE", "91")

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

# --- i18n -------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"  # times are stored in UTC and shown in each user's local time by the browser
USE_I18N = True
USE_TZ = True

# --- Static files -----------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
WHITENOISE_USE_FINDERS = DEBUG
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Uploaded files (profile photos) ----------------------------------------
# NOTE: on Render's free plan the disk is wiped on every deploy. For permanent
# photos, attach a Render Disk and point MEDIA_ROOT at it (env MEDIA_ROOT).
MEDIA_URL = "/media/"
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", str(BASE_DIR / "media"))
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024

# --- Production security ----------------------------------------------------
if not DEBUG:
    # Render terminates TLS in front of the app and forwards this header.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True


# =============================================================================
# FREE LIMITS & PAID PACKS  <- change the numbers here (or with the env vars)
# =============================================================================
# Free messages every user gets per day. Change a number and restart the server:
# the chat, the landing page and the pricing page all follow it.
FREE_DAILY_LIMITS = {
    "text": env_int("FREE_TEXT_PER_DAY", 20),    # text messages
    "voice": env_int("FREE_VOICE_PER_DAY", 5),   # audio / voice messages
    "image": env_int("FREE_IMAGES_PER_DAY", 5),  # photos
}
# How many "Suggested for you" profiles each user sees in the chat sidebar.
#   free  -> users who have never bought a pack
#   paid  -> users with at least one paid order
RECOMMENDED_PROFILES = {
    "free": env_int("FREE_RECOMMENDED_PROFILES", 5),
    "paid": env_int("PAID_RECOMMENDED_PROFILES", 10),
}
# The daily counters reset at midnight in this timezone (any name from the IANA list, e.g. "Asia/Kolkata").
LIMITS_TIMEZONE = os.environ.get("LIMITS_TIMEZONE", "UTC")

# Packs people can buy when the free messages run out. Bought messages are used only after
# the free ones for the day, and they never expire. `price` is in whole currency units.
PAYMENT_CURRENCY = os.environ.get("PAYMENT_CURRENCY", "INR")
PAYMENT_CURRENCY_SYMBOL = os.environ.get("PAYMENT_CURRENCY_SYMBOL", "₹")
CREDIT_PACKS = [
    {"id": "starter", "name": "Starter", "price": 49, "text": 200, "voice": 20, "image": 20},
    {"id": "plus", "name": "Plus", "price": 99, "text": 500, "voice": 50, "image": 50, "popular": True},
    {"id": "pro", "name": "Pro", "price": 249, "text": 1500, "voice": 150, "image": 150},
]

# --- Razorpay (payments) ------------------------------------------------------
# Leave these empty to keep payments off. While DEBUG is on and no keys are set,
# the "Buy" button runs a fake test payment so you can try the full flow.
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
