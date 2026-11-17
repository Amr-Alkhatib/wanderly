"""System checks for the presentation layer."""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def privacy_contact_configured(app_configs, **kwargs):
    """The privacy policy must name a contact for data protection requests."""
    if getattr(settings, "WANDERLY_CONTACT_EMAIL", ""):
        return []
    return [
        Error(
            "WANDERLY_CONTACT_EMAIL is not set, so /privacy/ shows no contact address.",
            hint="Add WANDERLY_CONTACT_EMAIL=<address> to the environment or the .env file.",
            id="web.E001",
        )
    ]
