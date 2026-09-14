from django.contrib import admin
from django.shortcuts import render
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _

from . import conf
from .models import Acceptance, DocType, LegalDocument


@admin.register(LegalDocument)
class LegalDocumentAdmin(admin.ModelAdmin):
    list_display = ("doc_type", "language", "version", "audience", "is_current",
                    "requires_acceptance", "requires_reacceptance", "published_at")
    list_filter = ("doc_type", "language", "audience", "is_current", "requires_acceptance")
    search_fields = ("title", "body_html")
    ordering = ("doc_type", "language", "-version")
    fieldsets = (
        (None, {"fields": ("doc_type", "language", "version", "audience", "title", "body_html")}),
        (_("Publication"), {
            "fields": ("is_current", "published_at",
                       "requires_acceptance", "requires_reacceptance"),
            "description": _(
                "Tick 'Force re-acceptance' ONLY for a substantive change: it blocks "
                "every user until they accept again. Never tick it for a typo fix."
            ),
        }),
    )

    @property
    def media(self):
        # Built per request, not at class-definition time: editor assets are a
        # setting, and a setting read at import cannot be overridden later.
        from django.forms import Media
        return super().media + Media(
            css={"all": conf.ADMIN_EDITOR_CSS},
            js=tuple(conf.ADMIN_EDITOR_JS) + ("consent_trail/admin-editor.js",),
        )

    def save_model(self, request, obj, form, change):
        # Sanitize on WRITE; views sanitize again on render (the design notes pattern).
        obj.body_html = import_string(conf.SANITIZER)(obj.body_html)
        super().save_model(request, obj, form, change)


@admin.register(Acceptance)
class AcceptanceAdmin(admin.ModelAdmin):
    """Read-only: this is evidence. Nothing here may be edited after the fact."""

    list_display = ("user", "doc_type", "version", "accepted_at",
                    "language_shown", "ip_address")
    list_filter = ("doc_type", "version", "language_shown")
    search_fields = ("user__username", "user__email", "ip_address")
    date_hierarchy = "accepted_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


    # ── Audit view: who has NOT accepted ─────────────────────────────────

    def get_urls(self):
        from django.urls import path

        return [
            path(
                "pending/",
                self.admin_site.admin_view(self.pending_view),
                name="consent_trail_pending",
            ),
        ] + super().get_urls()

    def pending_view(self, request):
        """Users who have not accepted the current version of each document.

        The whole point of collecting consent is being able to answer "who is
        missing?" — without this the acceptance log only tells you who complied.
        """
        from django.contrib.auth import get_user_model
        from django.core.paginator import Paginator

        from . import audience as audience_mod

        User = get_user_model()
        selected = request.GET.get("doc") or ""

        required = LegalDocument.acceptance_required()  # untargeted baseline
        targeted = {
            (d, v, a)
            for d, v, a in LegalDocument._required_rows()
            if a
        }

        blocks = []
        for doc_type, version, aud in sorted(
            {(d, v, "") for d, v in required.items()} | targeted
        ):
            if selected and doc_type != selected:
                continue

            accepted_ids = Acceptance.objects.filter(
                doc_type=doc_type, version=version
            ).values_list("user_id", flat=True)

            qs = User.objects.exclude(id__in=accepted_ids).order_by("username")
            if aud:
                # Targeted document: keep only users in that audience. Done in
                # Python because only the host project knows the mapping.
                ids = [u.id for u in qs if aud in audience_mod.tags_for(u)]
                qs = User.objects.filter(id__in=ids).order_by("username")

            page = Paginator(qs, 100).get_page(request.GET.get("page"))
            blocks.append({
                "doc_type": doc_type,
                "label": DocType(doc_type).label,
                "version": version,
                "audience": aud,
                "total": qs.count(),
                "page": page,
            })

        context = {
            **self.admin_site.each_context(request),
            "title": _("Pending acceptances"),
            "blocks": blocks,
            "doc_choices": DocType.choices,
            "selected": selected,
            "opts": self.model._meta,
        }
        return render(request, "consent_trail/admin/pending.html", context)
