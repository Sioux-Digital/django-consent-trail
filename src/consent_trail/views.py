from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.module_loading import import_string
from django.utils.safestring import mark_safe
from django.utils.translation import get_language

from . import conf
from .models import DocType, Acceptance, LegalDocument

def _render_body(doc):
    """Sanitize on render as well as on write — DB content could in theory be
    tampered with through another path.

    Resolved per call, not memoised at import: a setting read once at import
    time freezes whatever was configured then and breaks override_settings.
    """
    return mark_safe(import_string(conf.SANITIZER)(doc.body_html))


def document(request, slug):
    """Public page for one legal document. Anonymous access on purpose."""
    if slug not in DocType.values:
        raise Http404("Unknown legal document")

    user = request.user if request.user.is_authenticated else None
    doc, is_fallback = LegalDocument.resolve(slug, get_language(), user=user)
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
        doc, is_fallback = LegalDocument.resolve(doc_type, language, user=request.user)
        if doc is not None:
            # Body rendered inline so the text is genuinely presented, not just
            # linked — a link nobody clicks is weak evidence of informed consent.
            # `is_fallback` travels with it: the screen that records consent is
            # exactly where "this is not the text that binds you" has to appear.
            documents.append({
                "doc": doc,
                "body": _render_body(doc),
                "is_fallback": is_fallback,
            })

    # Validate on the way IN as well, so a hostile URL never reaches the
    # hidden input in the first place. Belt and braces with the POST check.
    raw_next = request.POST.get("next") if request.method == "POST" else request.GET.get("next")
    checked = safe_next(request, raw_next)
    return {
        "base_template": conf.BASE_TEMPLATE,
        "documents": documents,
        "fallback_language": conf.FALLBACK_LANGUAGE,
        "next": "" if checked == "/" else checked,
        "error": error,
    }


@login_required
def my_consents(request):
    """What this user has accepted, and when. Linked from a profile page."""
    accepted = {
        (a.doc_type, a.version): a
        for a in Acceptance.objects.filter(user=request.user)
    }
    required = LegalDocument.acceptance_required(request.user)
    language = get_language()

    rows = []
    seen = set()
    for doc_type, version in required.items():
        doc, _fb = LegalDocument.resolve(doc_type, language, user=request.user)
        seen.add((doc_type, version))
        rows.append({
            "doc_type": doc_type,
            "title": doc.title if doc else doc_type,
            "version": version,
            "acceptance": accepted.get((doc_type, version)),
        })

    # Documents accepted in the past that are no longer required — the proof
    # still belongs to the user and must remain visible.
    for (doc_type, version), acc in sorted(accepted.items()):
        if (doc_type, version) in seen:
            continue
        doc, _fb = LegalDocument.resolve(doc_type, language, user=request.user)
        rows.append({
            "doc_type": doc_type,
            "title": doc.title if doc else doc_type,
            "version": version,
            "acceptance": acc,
            "superseded": True,
        })

    return render(request, "consent_trail/my_consents.html", {
        "base_template": conf.BASE_TEMPLATE,
        "rows": rows,
    })
