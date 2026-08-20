"""Django settings for Muellima."""
from pathlib import Path
from decimal import Decimal
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "dev-insecure-key-change-me-in-production-1234567890",
)
DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() in ("true", "1", "yes")
MOCK = os.environ.get("MOCK", "False").lower() in ("true", "1", "yes")


def env_list(name: str, default: str = "") -> list[str]:
    return [value.strip() for value in os.environ.get(name, default).split(",") if value.strip()]


ALLOWED_HOSTS = ["*"] if DEBUG else env_list(
    "DJANGO_ALLOWED_HOSTS",
    "muellima.com,www.muellima.com",
)
CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
    "https://muellima.com,https://www.muellima.com",
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.facebook",
    "school",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "school.middleware.PageVisitMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "school.context_processors.social_auth",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": 
"django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": 
"django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": 
"django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "it-it"
TIME_ZONE = "Europe/Rome"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = []
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Enable only behind a trusted proxy that overwrites X-Real-IP/X-Forwarded-For.
TRUST_PROXY_IP_HEADERS = os.environ.get("TRUST_PROXY_IP_HEADERS", "False").lower() in ("true", "1", "yes")
TRUST_HTTPS_PROXY = os.environ.get("TRUST_HTTPS_PROXY", "False").lower() in ("true", "1", "yes")
if TRUST_HTTPS_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
ACCOUNT_UNIQUE_EMAIL = True
SOCIALACCOUNT_LOGIN_ON_GET = False

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
FACEBOOK_APP_ID = os.environ.get("FACEBOOK_APP_ID", "")
FACEBOOK_APP_SECRET = os.environ.get("FACEBOOK_APP_SECRET", "")

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "OAUTH_PKCE_ENABLED": True,
        "APPS": ([{
            "client_id": GOOGLE_CLIENT_ID,
            "secret": GOOGLE_CLIENT_SECRET,
            "key": "",
        }] if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET else []),
    },
    "facebook": {
        "METHOD": "oauth2",
        "SCOPE": ["email", "public_profile"],
        "FIELDS": ["id", "email", "name", "first_name", "last_name"],
        "APPS": ([{
            "client_id": FACEBOOK_APP_ID,
            "secret": FACEBOOK_APP_SECRET,
            "key": "",
        }] if FACEBOOK_APP_ID and FACEBOOK_APP_SECRET else []),
    },
}

# ── OpenAI configuration (all server-side) 
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_REALTIME_MODEL = os.environ.get("OPENAI_REALTIME_MODEL", 
"gpt-realtime-2.1")
OPENAI_TEXT_MODEL = os.environ.get("OPENAI_TEXT_MODEL", "gpt-4o-2024-11-20")
OPENAI_IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
OPENAI_REALTIME_VOICE = os.environ.get("OPENAI_REALTIME_VOICE", "alloy")
OPENAI_TIMEOUT = 60  # seconds
AGENT_MAX_ITERATIONS = int(os.environ.get("AGENT_MAX_ITERATIONS", "2"))

# Dashboard-only cost estimates. OpenAI prices are expressed in USD.
OPENAI_TEXT_INPUT_USD_PER_1M = Decimal(os.environ.get("OPENAI_TEXT_INPUT_USD_PER_1M", "2.50"))
OPENAI_TEXT_OUTPUT_USD_PER_1M = Decimal(os.environ.get("OPENAI_TEXT_OUTPUT_USD_PER_1M", "10.00"))
OPENAI_REALTIME_TEXT_INPUT_USD_PER_1M = Decimal(os.environ.get("OPENAI_REALTIME_TEXT_INPUT_USD_PER_1M", "4.00"))
OPENAI_REALTIME_TEXT_OUTPUT_USD_PER_1M = Decimal(os.environ.get("OPENAI_REALTIME_TEXT_OUTPUT_USD_PER_1M", "24.00"))
OPENAI_REALTIME_AUDIO_INPUT_USD_PER_1M = Decimal(os.environ.get("OPENAI_REALTIME_AUDIO_INPUT_USD_PER_1M", "32.00"))
OPENAI_REALTIME_AUDIO_OUTPUT_USD_PER_1M = Decimal(os.environ.get("OPENAI_REALTIME_AUDIO_OUTPUT_USD_PER_1M", "64.00"))
OPENAI_IMAGE_USD_PER_IMAGE = Decimal(os.environ.get("OPENAI_IMAGE_USD_PER_IMAGE", "0.042"))

MIN_LESSON = int(os.environ.get("MIN_LESSON", "10"))
MAX_LESSON = int(os.environ.get("MAX_LESSON", "24"))
FREE_TRIAL_MINUTES = int(os.environ.get("FREE_TRIAL_MINUTES", "5"))
MOCK_TIME = int(os.environ.get("MOCK_TIME", "0"))

USERS_WHITELIST = {
    email.strip().casefold()
    for email in os.environ.get("USERS_WHITELIST", "").split(",")
    if email.strip()
}

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

if MIN_LESSON < 1:
    raise ValueError("MIN_LESSON deve essere almeno 1")
if MAX_LESSON < MIN_LESSON:
    raise ValueError("MAX_LESSON deve essere maggiore o uguale a MIN_LESSON")
if FREE_TRIAL_MINUTES < 0:
    raise ValueError("FREE_TRIAL_MINUTES non può essere negativo")
if MOCK_TIME < 0:
    raise ValueError("MOCK_TIME non può essere negativo")
if not 1 <= AGENT_MAX_ITERATIONS <= 3:
    raise ValueError("AGENT_MAX_ITERATIONS deve essere compreso tra 1 e 3")

# Application logs must remain visible in the runserver console, including
# exceptions raised while calling external AI and payment services.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "school": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
