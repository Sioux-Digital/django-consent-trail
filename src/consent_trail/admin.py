from django.contrib import admin
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _

from . import conf
from .models import Acceptance, LegalDocument

_sanitize = import_string(conf.SANITIZER)


@admin.register(LegalDocument)
class LegalDocumentAdmin(admin.ModelAdmin):
    list_display = ("doc_type", "language", "version", "is_current",
                    "requires_acceptance", "requires_reacceptance", "published_at")
    list_filter = ("doc_type", "language", "is_current", "requires_acceptance")
    search_fields = ("title", "body_html")
    ordering = ("doc_type", "language", "-version")
    fieldsets = (
        (None, {"fields": ("doc_type", "language", "version", "title", "body_html")}),
        (_("Publication"), {
            "fields": ("is_current", "published_at",
                       "requires_acceptance", "requires_reacceptance"),
            "description": _(
                "Tick 'Force re-acceptance' ONLY for a substantive change: it blocks "
                "every user until they accept again. Never tick it for a typo fix."
            ),
        }),
    )

    class Media:
        css = {"all": conf.ADMIN_EDITOR_CSS}
        js = tuple(conf.ADMIN_EDITOR_JS) + ("consent_trail/admin-editor.js",)

    def save_model(self, request, obj, form, change):
        # Sanitize on WRITE; views sanitize again on render (the design notes pattern).
        obj.body_html = _sanitize(obj.body_html)
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
