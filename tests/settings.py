"""Minimal project used to exercise the package standalone."""

SECRET_KEY = "test-only"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",
    "django.contrib.staticfiles",
    "consent_trail.apps.ConsentTrailConfig",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "consent_trail.middleware.AcceptanceMiddleware",
]

ROOT_URLCONF = "tests.urls"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True, "DIRS": [],
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

STATIC_URL = "/static/"
USE_TZ = True
USE_I18N = True
# "en" so UI assertions read the msgids themselves. The package now ships
# compiled catalogues, so running the suite under "fr" would translate every
# page and make an assertion on wording a test of our own translation rather
# than of the view. Tests that care about a language set it locally with
# `self.settings(LANGUAGE_CODE=...)`.
LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("fr", "Francais"), ("es", "Espanol"), ("ja", "Japanese")]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
