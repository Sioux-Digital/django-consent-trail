from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ConsentTrailConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "consent_trail"
    verbose_name = _("Legal documents & consent")
