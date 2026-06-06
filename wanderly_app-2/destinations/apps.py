from django.apps import AppConfig


class DestinationsConfig(AppConfig):
    """The data layer: normalized, provenance-stamped travel facts."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "destinations"
    verbose_name = "Destinations (data layer)"
