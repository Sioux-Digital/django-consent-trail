from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.module_loading import import_string
from django.utils.safestring import mark_safe
from django.utils.translation import get_language

from . import conf
from .models import DocType, Acceptance, LegalDocument

#: Resolved once. Sanitizing on render as well as on write is deliberate —
#: DB content could in theory be tampered with through another path.
_sanitize = import_string(conf.SANITIZER)


def _render_body(doc):
    return mark_safe(_sanitize(doc.body_html))


def document(request, slug):
    """Public page for one legal document. Anonymous access on purpose."""
    if slug not in DocType.values:
        raise Http404("Unknown legal document")

    doc, is_fallback = LegalDocument.resolve(slug, get_language())
    if doc is None:
        raise Http404("This document has not been published yet")

    return render(
        request,
        "consent_trail/document.html",
        {
            "base_template": conf.BASE_TEMPLATE,
            "doc": doc,
            "body": _render_body(doc),
            "is_fallback": is_fallback,
            "fallback_language": conf.FALLBACK_LANGUAGE,
        },
    )


def safe_next(request, raw):
    """Return ``raw`` only if it points back at this site, else "/".

    Everyone lands on the acceptance screen after a terms update, which makes an
    unvalidated ``next`` a first-rate phishing vector: mail out
    ``/consent/accept/?next=https://evil.example``, the user accepts on the real
    domain and is handed to a fake login page while trusting the flow.
    """
    if raw and url_has_allowed_host_and_scheme(
        raw,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return raw
    return "/"


@login_required
def accept(request):
    """Re-acceptance screen: shown when a document changed substantively."""
    pending = Acceptance.pending_for(request.user)
    if not pending:
        return redirect("/")

    if request.method == "POST":
        if not request.POST.get("accept"):
            return render(
                request,
                "consent_trail/accept.html",
                _accept_context(request, pending, error=True),
            )
        for doc_type, version in pending.items():
            Acceptance.record(request.user, doc_type, version, request=request)
        return redirect(safe_next(request, request.POST.get("next")))

    return render(request, "consent_trail/accept.html", _accept_context(request, pending))


def _accept_context(request, pending, error=False):
    language = get_language()
    documents = []
    for doc_type in pending:
        doc, _fallback = LegalDocument.resolve(doc_type, language)
        if doc is not None:
            documents.append(doc)

    # Validate on the way IN as well, so a hostile URL never reaches the
    # hidden input in the first place. Belt and braces with the POST check.
    raw_next = request.POST.get("next") if request.method == "POST" else request.GET.get("next")
    checked = safe_next(request, raw_next)
    return {
        "base_template": conf.BASE_TEMPLATE,
        "documents": documents,
        "next": "" if checked == "/" else checked,
        "error": error,
    }
