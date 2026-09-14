"""Template helpers for linking legal documents.

Linking every document type unconditionally produces 404s for the ones not
published yet — worse than no link at all, because a visitor clicking "Terms of
Sale" in a footer expects a page. These helpers only ever yield what exists.
"""

from django import template
from django.utils.translation import get_language

from ..models import DocType, LegalDocument

register = template.Library()


@register.simple_tag(takes_context=True)
def legal_documents(context):
    """Published documents for the current language, as ``[(slug, title)]``.

    Falls back the same way the detail view does, so a document published only
    in the fallback language still gets a link.
    """
    request = context.get("request")
    user = getattr(request, "user", None) if request else None
    if user is not None and not getattr(user, "is_authenticated", False):
        user = None

    language = get_language()
    out = []
    for slug in DocType.values:
        doc, _fallback = LegalDocument.resolve(slug, language, user=user)
        if doc is not None:
            out.append((slug, doc.title))
    return out
