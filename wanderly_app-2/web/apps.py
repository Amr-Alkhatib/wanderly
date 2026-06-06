from django.apps import AppConfig


class WebConfig(AppConfig):
    """Presentation layer: views, URLs, and template wiring."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "web"
    verbose_name = "Web (presentation)"
