from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
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

    # Someone reading their own terms wants to know when they agreed to them —
    # and the version they agreed to, which is not always the one on screen.
    acceptance = None
    if user is not None:
        acceptance = (
            Acceptance.objects.filter(user=user, doc_type=slug)
            .order_by("-accepted_at")
            .first()
        )

    return render(
        request,
        "consent_trail/document.html",
        {
            "base_template": conf.BASE_TEMPLATE,
            "doc": doc,
            "body": _render_body(doc),
            "is_fallback": is_fallback,
            "fallback_language": conf.FALLBACK_LANGUAGE,
            "acceptance": acceptance,
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
    """Signature screen: one row per document, signed one at a time.

    Deliberately NOT one global checkbox over every document inlined on the page.
    Each document is opened on its own page and signed on its own POST, so the
    ``Acceptance`` rows carry genuinely different timestamps — "I accepted the
    privacy policy at 16:04 and the terms of sale at 16:07" is a far better
    record than three rows stamped the same second by one click.

    Trade-off accepted: the binding text is now behind a link the user must open
    rather than scrolled inline. Weaker presentation evidence, much clearer
    per-document consent. Chosen by the product owner.
    """
    pending = Acceptance.pending_for(request.user)

    if request.method == "POST":
        doc_type = request.POST.get("doc_type")
        if doc_type not in pending:
            # Already signed in another tab, or a forged/stale field. Re-render
            # rather than error: the state below is the truth.
            return redirect(_self_url(request, request.POST.get("next"), signed=True))
        Acceptance.record(request.user, doc_type, pending[doc_type], request=request)
        return redirect(_self_url(request, request.POST.get("next"), signed=True))

    # Nothing to sign and no signature just made → this page has no purpose.
    # `signed` keeps the confirmation step visible after the last signature
    # instead of bouncing the user off mid-flow.
    if not pending and not request.GET.get("signed"):
        return redirect(safe_next(request, request.GET.get("next")))

    return render(request, "consent_trail/accept.html", _accept_context(request, pending))


def _self_url(request, raw_next, signed=False):
    """This view's URL, preserving a validated ``next``."""
    params = {}
    checked = safe_next(request, raw_next)
    if checked != "/":
        params["next"] = checked
    if signed:
        params["signed"] = "1"
    url = reverse("consent_trail:accept")
    return f"{url}?{urlencode(params)}" if params else url


def _accept_context(request, pending):
    """Rows for every document requiring consent, pending or already signed.

    Showing the already-signed ones costs no extra state and reads better than a
    list that silently shrinks: the user sees their whole standing agreement,
    with the one line that needs action standing out.
    """
    language = get_language()
    required = LegalDocument.acceptance_required(request.user)

    signed_rows = {}
    for acceptance in Acceptance.objects.filter(
        user=request.user, doc_type__in=required
    ).order_by("accepted_at"):
        signed_rows[acceptance.doc_type] = acceptance  # keep the latest

    rows = []
    for doc_type, version in sorted(required.items()):
        doc, is_fallback = LegalDocument.resolve(doc_type, language, user=request.user)
        if doc is None:
            continue
        rows.append({
            "doc": doc,
            "doc_type": doc_type,
            "version": version,
            "is_fallback": is_fallback,
            "pending": doc_type in pending,
            "acceptance": signed_rows.get(doc_type),
        })

    # Validate on the way IN as well, so a hostile URL never reaches the hidden
    # input in the first place. Belt and braces with the POST check.
    raw_next = request.POST.get("next") if request.method == "POST" else request.GET.get("next")
    checked = safe_next(request, raw_next)
    return {
        "base_template": conf.BASE_TEMPLATE,
        "rows": rows,
        "pending_count": len(pending),
        "fallback_language": conf.FALLBACK_LANGUAGE,
        "next": "" if checked == "/" else checked,
        "continue_url": checked,
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
