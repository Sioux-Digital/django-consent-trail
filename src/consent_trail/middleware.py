"""Force re-acceptance when a document changed substantively.

Same shape as core.middleware.OnboardingMiddleware (exempt-prefix tuple + early
redirect), but it must NOT import from it — this app ships standalone.

Ordering: goes LAST in MIDDLEWARE, after authentication and after the onboarding
and MFA middlewares. Getting a user through signup and MFA matters more than a
terms update.
"""

import re

from django.shortcuts import redirect
from django.urls import reverse

from . import conf
from .models import Acceptance

#: "fr", "en", "pt-br" — the shape LocaleMiddleware prefixes URLs with.
_LANG_PREFIX = re.compile(r"[a-z]{2}(?:-[a-z]{2})?")


class AcceptanceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)

        if (
            user is not None
            and user.is_authenticated
            and not (conf.EXCLUDE_SUPERUSERS and user.is_superuser)
            and not self._is_exempt(request.path)
        ):
            if Acceptance.pending_for(user):
                url = reverse("consent_trail:accept")
                if request.path != url:
                    return redirect(f"{url}?next={request.path}")

        return self.get_response(request)

    @staticmethod
    def _is_exempt(path):
        # Strip the i18n language prefix so /fr/consent/... matches "/consent/".
        #
        # Must match the SHAPE of a language code, not merely its length: a
        # naive "2 or 5 characters" test eats "consent_trail" itself, leaves "/cgu/",
        # and the acceptance page redirects to itself forever — site down.
        # Caught by test_never_blocks_the_legal_pages_themselves.
        parts = path.split("/", 2)
        if len(parts) > 1 and _LANG_PREFIX.fullmatch(parts[1]):
            path = "/" + (parts[2] if len(parts) > 2 else "")
        return any(path.startswith(p) for p in conf.EXEMPT_PREFIXES)
