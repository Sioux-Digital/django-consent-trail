"""Consent capture at signup.

No allauth import on purpose — the app must install anywhere.
``signup(request, user)`` happens to be the hook name django-allauth calls on
``ACCOUNT_SIGNUP_FORM_CLASS``; it is a thin alias over ``record_consent()`` so
any other auth stack can call the generic method instead.
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import DocType, Acceptance, LegalDocument


class ConsentForm(forms.Form):
    """Adds a required consent checkbox and writes the proof after signup."""

    accept_legal = forms.BooleanField(
        required=True,
        label=_("I have read and accept the Terms of Use and the Privacy Policy."),
        error_messages={
            "required": _("You must accept the terms to create an account."),
        },
    )

    field_order = ["accept_legal"]

    def record_consent(self, user, request=None):
        """Write one acceptance row per document currently requiring consent."""
        # No audience at signup: the user has no memberships yet, so only
        # untargeted documents can meaningfully be presented.
        for doc_type, version in LegalDocument.acceptance_required(user).items():
            Acceptance.record(user, doc_type, version, request=request)

    # django-allauth calls this after the user row exists.
    def signup(self, request, user):
        self.record_consent(user, request=request)


def consent_links():
    """``[(doc_type, title)]`` for the documents a new user must accept.

    Lets the signup template link the real documents instead of hardcoding
    labels that drift from what is actually published.
    """
    required = LegalDocument.acceptance_required()
    if not required:
        return []
    docs = LegalDocument.objects.filter(
        doc_type__in=required, is_current=True
    ).values_list("doc_type", "title")
    seen, out = set(), []
    for doc_type, title in docs:
        if doc_type not in seen:
            seen.add(doc_type)
            out.append((doc_type, title))
    return out or [(d, DocType(d).label) for d in required]
