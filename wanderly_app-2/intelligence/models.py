"""
Intelligence-layer models.

These tables hold *derived* signals and *user* state -- never raw facts
(those live in `destinations`). Keeping them separate means the scoring
engine reads a clean, typed surface and the ABSA / scraping pipeline can
write into `CityAspectScore` without touching identity data.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from destinations.models import ActivityCategory, City


class CityAspectScore(models.Model):
    """
    A per-city, per-aspect sentiment score -- the structured output of the
    ABSA (aspect-based sentiment analysis) model run over scraped reviews.

    The recommender treats these as *interest-match* evidence: if a user
    cares about 'food', the food aspect score feeds their interest factor.
    Scores are stored 0-100 with a sample size so confidence can be shown.
    """

    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name="aspect_scores")
    aspect = models.CharField(max_length=20, choices=ActivityCategory.choices, db_index=True)
    score = models.PositiveSmallIntegerField(help_text="0-100 sentiment score for this aspect.")
    sample_size = models.PositiveIntegerField(
        default=0, help_text="Number of reviews the score was derived from."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["city", "aspect"]
        constraints = [
            models.UniqueConstraint(fields=["city", "aspect"], name="uniq_aspect_per_city"),
            models.CheckConstraint(
                condition=models.Q(score__gte=0) & models.Q(score__lte=100),
                name="aspect_score_in_range",
            ),
        ]
        indexes = [models.Index(fields=["city", "aspect"], name="idx_aspect_city")]

    def __str__(self) -> str:
        return f"{self.city.name} · {self.aspect} = {self.score}"


class UserProfile(models.Model):
    """
    A traveller's stated preferences, used to weight the recommendation.
    One-to-one with the auth user so the engine can personalise results.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="travel_profile"
    )
    max_daily_budget_eur = models.PositiveIntegerField(default=100)
    travel_month = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="1-12; null means flexible."
    )
    preferred_climate = models.CharField(max_length=20, blank=True)
    safety_priority = models.PositiveSmallIntegerField(
        default=3, help_text="1 (don't care) .. 5 (critical)."
    )
    interests = models.JSONField(
        default=list, blank=True, help_text="List of ActivityCategory values."
    )

    def __str__(self) -> str:
        return f"Profile<{self.user}>"


class SavedTrip(models.Model):
    """A city a user has bookmarked, with the score captured at save time."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_trips"
    )
    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name="saved_by")
    saved_at = models.DateTimeField(auto_now_add=True)
    score_at_save = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-saved_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "city"], name="uniq_saved_city_per_user")
        ]

    def __str__(self) -> str:
        return f"{self.user} saved {self.city.name}"
