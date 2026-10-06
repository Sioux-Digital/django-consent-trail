"""Settings for consent_trail, with defaults.

Read **lazily**, on attribute access, never at import time. That matters for a
reusable package: settings read at import freeze whatever was configured when
the module first loaded, which silently breaks ``override_settings`` in a host
project's test suite and any runtime reconfiguration.

Usage stays ordinary::

    from . import conf
    conf.AUTHORITATIVE_LANGUAGE
"""

from django.conf import settings

DEFAULTS = {
    #: Template the public pages extend. Kept injectable so the app renders
    #: standalone (its own bare ``consent_trail/base.html``) or inside a host
    #: project's layout — hardcoding ``{% extends %}`` is what makes an app
    #: impossible to reuse.
    "BASE_TEMPLATE": "consent_trail/base.html",

    #: The language whose text legally prevails — and therefore the one served
    #: when the requested language has no published version. The prevalence
    #: notice names this language to the reader, so setting it to "de" makes the
    #: notice say German: never hardcode a language name in a legal notice.
    #:
    #: One setting for both meanings on purpose. They are the same language in
    #: every real jurisdiction: you fall back to the authoritative text because
    #: it is the one that binds. Split them only if a real case turns up.
    "AUTHORITATIVE_LANGUAGE": "fr",

    #: Where to read the client IP for the acceptance proof.
    #: Behind a CDN or reverse proxy, REMOTE_ADDR is the proxy — every consent
    #: record would log the same wrong address, which voids the proof.
    #: Only trust a header you control end to end.
    "IP_HEADER_NAME": "HTTP_CF_CONNECTING_IP",

    #: Seconds to cache "which documents currently require acceptance".
    #: The middleware runs on every request; without this it is a query per
    #: page view.
    "CACHE_SECONDS": 300,

    #: Never lock superusers out over a misconfigured flag.
    "EXCLUDE_SUPERUSERS": True,

    #: Paths the re-acceptance middleware must never intercept. The acceptance
    #: screen and the document pages MUST be here or the redirect loops.
    "EXEMPT_PREFIXES": (
        "/legal/", "/consent/", "/accounts/", "/admin/",
        "/i18n/", "/static/", "/media/", "/favicon.ico",
    ),

    #: Dotted path to the HTML sanitizer callable, ``f(str) -> str``.
    #: Point it at your own only if you genuinely need a different allowlist —
    #: a sanitizer tuned for user-generated content will often strip things a
    #: legal document legitimately contains.
    "SANITIZER": "consent_trail.sanitizer.clean_html",

    #: Editor assets injected into the admin change form, as static paths.
    #: Empty means a plain textarea, which works standalone.
    "ADMIN_EDITOR_CSS": (),
    "ADMIN_EDITOR_JS": (),

    #: Dotted path to ``f(user) -> set[str]`` returning the audience tags a user
    #: belongs to. Lets a host project target re-acceptance at a subset of users
    #: (one organisation, one plan, one country) without this package ever
    #: knowing what an "organisation" is. Example::
    #:
    #:     def resolve_audience(user):
    #:         return {f"org:{m.organization_id}" for m in user.memberships.all()}
    #:
    #: A document with an empty ``audience`` applies to everyone — the default,
    #: which covers the "all users" case with no configuration at all.
    "AUDIENCE_RESOLVER": "consent_trail.audience.everyone",
}

#: Settings whose value must end up as a tuple even when given a list.
_TUPLES = {"EXEMPT_PREFIXES", "ADMIN_EDITOR_CSS", "ADMIN_EDITOR_JS"}

PREFIX = "CONSENT_TRAIL_"


def __getattr__(name):
    """Resolve ``conf.X`` to ``settings.CONSENT_TRAIL_X`` or the default."""
    try:
        default = DEFAULTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no setting {name!r}") from None
    value = getattr(settings, PREFIX + name, default)
    return tuple(value) if name in _TUPLES else value


def __dir__():
    return sorted(DEFAULTS)
