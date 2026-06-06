from django.apps import AppConfig


class IntelligenceConfig(AppConfig):
    """The intelligence layer: deterministic, explainable ranking."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "intelligence"
    verbose_name = "Intelligence (scoring & explanation)"
