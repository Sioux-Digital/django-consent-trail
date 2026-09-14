"""Settings for the `legal` app, with defaults.

Every knob is read through ``getattr(settings, ...)`` so the app can be lifted
out into a standalone package without touching the project. Nothing
here imports from the host project.
"""

from django.conf import settings

#: Template the public pages extend. Kept injectable so the app renders
#: standalone (its own bare ``legal/base.html``) or inside a host project's
#: layout. See the design notes — hardcoding ``{% extends %}`` is what makes an app
#: impossible to extract.
BASE_TEMPLATE = getattr(settings, "CONSENT_TRAIL_BASE_TEMPLATE", "consent_trail/base.html")

#: Language served when the requested one has no published version.
#: The prevalence notice is shown whenever we fall back.
FALLBACK_LANGUAGE = getattr(settings, "CONSENT_TRAIL_FALLBACK_LANGUAGE", "fr")

#: Where to read the client IP for the acceptance proof.
#: Behind Cloudflare, REMOTE_ADDR is a Cloudflare IP — every consent record
#: would log the same wrong address, which destroys the proof. Idea borrowed
#: from django-termsandconditions' TERMS_IP_HEADER_NAME.
IP_HEADER_NAME = getattr(settings, "CONSENT_TRAIL_IP_HEADER_NAME", "HTTP_CF_CONNECTING_IP")

#: Seconds to cache "which documents currently require acceptance".
#: The middleware runs on every request; without this it is a guaranteed
#: query per page view.
CACHE_SECONDS = getattr(settings, "CONSENT_TRAIL_CACHE_SECONDS", 300)

#: Never lock superusers out over a misconfigured flag.
EXCLUDE_SUPERUSERS = getattr(settings, "CONSENT_TRAIL_EXCLUDE_SUPERUSERS", True)

#: Paths the re-acceptance middleware must never intercept. The acceptance
#: screen itself and the document pages MUST be here or the redirect loops.
EXEMPT_PREFIXES = tuple(
    getattr(
        settings,
        "CONSENT_TRAIL_EXEMPT_PREFIXES",
        ("/consent/", "/accounts/", "/admin/", "/i18n/", "/static/", "/media/", "/favicon.ico"),
    )
)

#: Dotted path to the HTML sanitizer callable, ``f(str) -> str``.
#: Defaults to the app's own nh3 wrapper.
#: Point it at your own callable only if you genuinely need a different
#: allowlist — a host sanitizer tuned for user-generated content will often
#: strip things a legal document legitimately contains.
SANITIZER = getattr(settings, "CONSENT_TRAIL_SANITIZER", "consent_trail.sanitizer.clean_html")

#: Editor assets injected into the admin change form, as static paths.
#: Empty by default: the app renders a plain textarea and works standalone.
#: A host project points these at its own editor assets so legal
#: documents are edited with the same editor as tickets.
ADMIN_EDITOR_CSS = tuple(getattr(settings, "CONSENT_TRAIL_ADMIN_EDITOR_CSS", ()))
ADMIN_EDITOR_JS = tuple(getattr(settings, "CONSENT_TRAIL_ADMIN_EDITOR_JS", ()))
