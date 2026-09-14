"""Legal documents and proof of acceptance.

Design note — the one thing that matters here:

``Acceptance`` stores the **coordinates** ``(doc_type, version)`` instead of
a ForeignKey to a ``LegalDocument`` row. A FK would bind acceptance to one
*language*, so someone who accepted the CGU in French and then switched the UI
to English would read as never having accepted. Legally wrong: you accept *the
document*, not *a translation of it*. This is exactly what disqualified both
django-termsandconditions and django-tos.

Price paid: the policy fields (``published_at``, ``requires_*``) are duplicated
across the language rows of one version. ``save()`` keeps them in sync, which is
far simpler than a third grouping model.
"""

import uuid

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from . import conf


class DocType(models.TextChoices):
    MENTIONS = "mentions", _("Legal notice")
    PRIVACY = "privacy", _("Privacy policy")
    CGU = "cgu", _("Terms of use")
    CGV = "cgv", _("Terms of sale")


_PENDING_CACHE_KEY = "consent_trail.acceptance_required"


class LegalDocument(models.Model):
    """One language rendering of one version of one legal document.

    ``version`` is shared across languages: ``(cgu, fr, 3)`` and ``(cgu, en, 3)``
    are the same document, rendered twice.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    doc_type = models.CharField(_("Document"), max_length=20, choices=DocType.choices)
    language = models.CharField(
        _("Language"), max_length=10,
        help_text=_("Language code, e.g. fr. Same version number across languages."),
    )
    version = models.PositiveIntegerField(
        _("Version"), default=1,
        help_text=_("Shared by every language of the same document version."),
    )

    title = models.CharField(_("Title"), max_length=200)
    body_html = models.TextField(_("Body"), blank=True)

    is_current = models.BooleanField(
        _("Current version"), default=False,
        help_text=_("Only one version per document and language can be current."),
    )
    published_at = models.DateTimeField(_("Published at"), null=True, blank=True)

    requires_acceptance = models.BooleanField(
        _("Must be accepted"), default=True,
        help_text=_("Legal notices are informational — untick for those."),
    )
    requires_reacceptance = models.BooleanField(
        _("Force re-acceptance"), default=False,
        help_text=_(
            "Tick ONLY for a substantive change. Ticked, every user is blocked "
            "until they accept again — do not tick for a typo fix."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["doc_type", "language", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["doc_type", "language", "version"],
                name="uniq_legal_doc_version_per_language",
            ),
        ]
        indexes = [
            models.Index(fields=["doc_type", "language", "is_current"]),
        ]
        verbose_name = _("Legal document")
        verbose_name_plural = _("Legal documents")

    def __str__(self):
        return f"{self.get_doc_type_display()} [{self.language}] v{self.version}"

    def save(self, *args, **kwargs):
        if self.is_current and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

        siblings = LegalDocument.objects.filter(
            doc_type=self.doc_type, version=self.version
        ).exclude(pk=self.pk)

        # Policy is a property of the VERSION, not of a translation — keep the
        # language rows from drifting apart.
        siblings.update(
            published_at=self.published_at,
            requires_acceptance=self.requires_acceptance,
            requires_reacceptance=self.requires_reacceptance,
        )

        if self.is_current:
            LegalDocument.objects.filter(
                doc_type=self.doc_type, language=self.language, is_current=True
            ).exclude(pk=self.pk).update(is_current=False)

        cache.delete(_PENDING_CACHE_KEY)

    def delete(self, *args, **kwargs):
        cache.delete(_PENDING_CACHE_KEY)
        return super().delete(*args, **kwargs)

    # ── Lookups ──────────────────────────────────────────────────────────

    @classmethod
    def resolve(cls, doc_type, language):
        """Current document for ``language``, falling back when untranslated.

        Returns ``(document, is_fallback)``. ``is_fallback`` drives the
        "only the French version is authoritative" notice.
        """
        doc = cls.objects.filter(
            doc_type=doc_type, language=language, is_current=True
        ).first()
        if doc is not None:
            return doc, False

        fallback = cls.objects.filter(
            doc_type=doc_type, language=conf.FALLBACK_LANGUAGE, is_current=True
        ).first()
        return fallback, fallback is not None

    @classmethod
    def acceptance_required(cls):
        """``{doc_type: version}`` for every current document needing consent.

        Cached: the middleware calls this on every request.
        """
        cached = cache.get(_PENDING_CACHE_KEY)
        if cached is not None:
            return cached

        required = {}
        rows = cls.objects.filter(
            is_current=True, requires_acceptance=True
        ).values_list("doc_type", "version")
        for doc_type, version in rows:
            # Languages of one version agree (see save()); max() is belt and
            # braces against a hand-edited row.
            required[doc_type] = max(version, required.get(doc_type, 0))

        cache.set(_PENDING_CACHE_KEY, required, conf.CACHE_SECONDS)
        return required


class Acceptance(models.Model):
    """Proof that a user accepted one version of one document.

    Append-only in spirit: never rewrite a row, a new acceptance is a new row.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="legal_acceptances",
    )
    doc_type = models.CharField(max_length=20, choices=DocType.choices)
    version = models.PositiveIntegerField()

    language_shown = models.CharField(
        max_length=10, blank=True,
        help_text=_("Language actually displayed when consent was given."),
    )
    accepted_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-accepted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "doc_type", "version"],
                name="uniq_legal_acceptance_per_version",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "doc_type"]),
        ]
        verbose_name = _("Legal acceptance")
        verbose_name_plural = _("Legal acceptances")

    def __str__(self):
        return f"{self.user} accepted {self.doc_type} v{self.version}"

    @classmethod
    def pending_for(cls, user):
        """Doc types this user still has to accept, as ``{doc_type: version}``."""
        required = LegalDocument.acceptance_required()
        if not required:
            return {}

        accepted = set(
            cls.objects.filter(user=user, doc_type__in=required).values_list(
                "doc_type", "version"
            )
        )
        return {d: v for d, v in required.items() if (d, v) not in accepted}

    @classmethod
    def record(cls, user, doc_type, version, request=None):
        """Write the proof. Idempotent — re-accepting the same version is a no-op."""
        ip, agent, language = None, "", ""
        if request is not None:
            ip = client_ip(request)
            agent = request.META.get("HTTP_USER_AGENT", "")[:300]
            language = getattr(request, "LANGUAGE_CODE", "") or ""

        obj, _created = cls.objects.get_or_create(
            user=user,
            doc_type=doc_type,
            version=version,
            defaults={
                "ip_address": ip,
                "user_agent": agent,
                "language_shown": language,
            },
        )
        return obj


def client_ip(request):
    """Real client IP, read from a configurable header.

    ``REMOTE_ADDR`` is the reverse proxy behind Cloudflare — using it would
    stamp every consent record with the same wrong address and void the proof.
    Falls back to REMOTE_ADDR when the header is absent (local dev, no proxy).
    """
    raw = request.META.get(conf.IP_HEADER_NAME) or request.META.get("REMOTE_ADDR")
    if not raw:
        return None
    # A forwarded header can carry "client, proxy1, proxy2" — the client is first.
    return raw.split(",")[0].strip() or None
