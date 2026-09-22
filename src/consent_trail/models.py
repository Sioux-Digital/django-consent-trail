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

from . import audience as audience_mod
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

    audience = models.CharField(
        _("Audience"), max_length=100, blank=True, db_index=True,
        help_text=_(
            "Leave empty to target every user. Otherwise an audience tag your "
            "project resolves, e.g. org:3f2b… — see CONSENT_TRAIL_AUDIENCE_RESOLVER."
        ),
    )

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
                fields=["doc_type", "language", "version", "audience"],
                name="uniq_doc_version_per_language_and_audience",
            ),
        ]
        indexes = [
            models.Index(fields=["doc_type", "language", "is_current"]),
            models.Index(fields=["is_current", "requires_acceptance"]),
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
            doc_type=self.doc_type, version=self.version, audience=self.audience
        ).exclude(pk=self.pk)

        # Policy is a property of the VERSION, not of a translation — keep the
        # language rows from drifting apart.
        siblings.update(
            published_at=self.published_at,
            requires_acceptance=self.requires_acceptance,
            requires_reacceptance=self.requires_reacceptance,
        )

        if self.is_current:
            # Scoped by audience: publishing a version aimed at one
            # organisation must not unpublish another organisation's.
            LegalDocument.objects.filter(
                doc_type=self.doc_type, language=self.language,
                audience=self.audience, is_current=True,
            ).exclude(pk=self.pk).update(is_current=False)

        cache.delete(_PENDING_CACHE_KEY)

    def delete(self, *args, **kwargs):
        cache.delete(_PENDING_CACHE_KEY)
        return super().delete(*args, **kwargs)

    # ── Lookups ──────────────────────────────────────────────────────────

    @classmethod
    def resolve(cls, doc_type, language, user=None):
        """Current document for ``language``, falling back when untranslated.

        Returns ``(document, is_fallback)``. ``is_fallback`` drives the
        "only the French version is authoritative" notice.
        """
        tags = audience_mod.tags_for(user) if user is not None else set()

        def pick(lang):
            rows = cls.objects.filter(
                doc_type=doc_type, language=lang, is_current=True
            ).order_by("-audience")  # a targeted version wins over the generic one
            for row in rows:
                if audience_mod.applies_to(row.audience, tags):
                    return row
            return None

        doc = pick(language)
        if doc is not None:
            return doc, False

        # Django hands back whatever it was given, region included: "en-us",
        # "pt-br", "zh-hans". Documents are filed by base language. Without this
        # retry, a site whose LANGUAGE_CODE carries a region never matches its
        # own documents and every page quietly serves the fallback instead —
        # which reads as working, in the wrong language.
        base = (language or "").split("-")[0]
        if base and base != language:
            doc = pick(base)
            if doc is not None:
                return doc, False

        fallback = pick(conf.FALLBACK_LANGUAGE)
        return fallback, fallback is not None

    @classmethod
    def _required_rows(cls):
        """Cached ``[(doc_type, version, audience)]`` of documents needing consent.

        Cached as a flat list rather than per user: the middleware calls this on
        every request, and a per-user cache key would multiply entries by the
        number of users for no gain — the audience filter is a cheap set test.
        """
        cached = cache.get(_PENDING_CACHE_KEY)
        if cached is not None:
            return cached

        rows = sorted(
            set(
                cls.objects.filter(is_current=True, requires_acceptance=True)
                .values_list("doc_type", "version", "audience")
            )
        )
        cache.set(_PENDING_CACHE_KEY, rows, conf.CACHE_SECONDS)
        return rows

    @classmethod
    def acceptance_required(cls, user=None):
        """``{doc_type: version}`` this user must have accepted.

        With no user, returns the untargeted documents only.
        """
        tags = audience_mod.tags_for(user) if user is not None else set()
        required = {}
        for doc_type, version, aud in cls._required_rows():
            if not audience_mod.applies_to(aud, tags):
                continue
            # Languages of one version agree (see save()); max() is belt and
            # braces against a hand-edited row.
            required[doc_type] = max(version, required.get(doc_type, 0))
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
        required = LegalDocument.acceptance_required(user)
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
