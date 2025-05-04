from django.apps import AppConfig


class RepPortalConfig(AppConfig):  # Changed from CustomerPortalConfig
    default_auto_field = "django.db.models.BigAutoField"
    name = "rep_portal"
