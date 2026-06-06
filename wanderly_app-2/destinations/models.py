"""
Data-layer models for Wanderly.

Design principles encoded here:

* **Normalization & separation of concerns.** Slow-changing identity data
  (Country, City, Activity) is kept apart from fast-changing, time-grained
  observations (MonthlyWeather, CostSnapshot, SafetyAdvisory). A city's
  cost of living changes; the fact that the city exists does not.

* **Freshness is first-class.** Every volatile fact records *where it came
  from* (`source`) and *when it was captured* (`captured_at`). The
  intelligence layer reads `is_stale` to decide whether a score should be
  flagged as based on aging data -- this is the "freshness-aware" promise.

* **Explainability needs structured numbers, not prose.** Scores are stored
  as small integers on 0-100 scales so the ranking engine can show exactly
  which factor contributed what. We never store a single opaque "rating".

The database is the product's differentiator; the LLM is a swappable
presentation layer on top of it.
"""

from __future__ import annotations

import datetime as _dt

from django.db import models
from django.utils import timezone
from django.utils.text import slugify


# --- Shared choices ----------------------------------------------------------


class Region(models.TextChoices):
    """Coarse continental grouping, used for filtering on the Explore page."""

    EUROPE = "europe", "Europe"
    ASIA = "asia", "Asia"
    AFRICA = "africa", "Africa"
    NORTH_AMERICA = "north_america", "North America"
    SOUTH_AMERICA = "south_america", "South America"
    OCEANIA = "oceania", "Oceania"
    MIDDLE_EAST = "middle_east", "Middle East"


class BudgetTier(models.IntegerChoices):
    """The familiar $ / $$ / $$$ shorthand, stored ordinally so it sorts."""

    BUDGET = 1, "$ Budget"
    MID_RANGE = 2, "$$ Mid-range"
    LUXURY = 3, "$$$ Luxury"


class ActivityCategory(models.TextChoices):
    """The traveller-interest taxonomy shared with the recommender."""

    BEACH = "beach", "Beach"
    MOUNTAINS = "mountains", "Mountains"
    CITY = "city", "City"
    CULTURAL = "cultural", "Cultural"
    NATURE = "nature", "Nature"
    ADVENTURE = "adventure", "Adventure"
    FOOD = "food", "Food"


class DataSource(models.TextChoices):
    """Provenance of a volatile fact -- shown to users and auditors alike."""

    MANUAL = "manual", "Manually curated"
    REDDIT = "reddit", "Reddit (PRAW)"
    OPEN_METEO = "open_meteo", "Open-Meteo API"
    NUMBEO = "numbeo", "Numbeo"
    GOV_ADVISORY = "gov_advisory", "Government travel advisory"
    SEED = "seed", "Demo seed data"


# --- Identity (slow-changing) ------------------------------------------------


class Country(models.Model):
    """A sovereign country. Identity data only -- nothing time-sensitive."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    region = models.CharField(max_length=20, choices=Region.choices, db_index=True)
    language = models.CharField(max_length=100, blank=True)
    currency = models.CharField(max_length=60, blank=True, help_text="e.g. 'Japanese Yen (¥)'")
    visa_summary = models.TextField(
        blank=True,
        help_text="Short free-text summary of visa rules for common nationalities.",
    )

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "countries"

    def __str__(self) -> str:
        return self.name

    def save(self, *args: object, **kwargs: object) -> None:
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class City(models.Model):
    """
    A city -- the primary unit users browse, compare and that the
    recommender ranks. Carries a short editorial summary plus its budget
    tier and primary category; all *quantitative* freshness-sensitive data
    lives in the related snapshot tables below.
    """

    country = models.ForeignKey(Country, on_delete=models.CASCADE, related_name="cities")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    summary = models.TextField(blank=True)

    primary_category = models.CharField(
        max_length=20,
        choices=ActivityCategory.choices,
        default=ActivityCategory.CITY,
        db_index=True,
    )
    budget_tier = models.PositiveSmallIntegerField(
        choices=BudgetTier.choices,
        default=BudgetTier.MID_RANGE,
        db_index=True,
    )
    emoji = models.CharField(
        max_length=8, blank=True, help_text="Decorative glyph used in card placeholders."
    )
    image = models.CharField(
        max_length=120,
        blank=True,
        help_text=(
            "Optional static image filename for the card (e.g. 'japan.png'), "
            "served from static/images/dest/. Presentation-only; falls back to "
            "the emoji placeholder when blank."
        ),
    )
    card_pill = models.CharField(
        max_length=40,
        blank=True,
        help_text="Optional editorial tag shown on Discover cards (e.g. 'Trending').",
    )
    is_featured = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "cities"
        constraints = [
            models.UniqueConstraint(
                fields=["country", "name"], name="uniq_city_per_country"
            )
        ]
        indexes = [
            # The Explore page filters on (region via country) + budget +
            # category; this composite index serves the common query.
            models.Index(fields=["primary_category", "budget_tier"], name="idx_city_cat_budget"),
        ]

    def __str__(self) -> str:
        return f"{self.name}, {self.country.name}"

    def save(self, *args: object, **kwargs: object) -> None:
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def budget_symbol(self) -> str:
        """Render the budget tier as '$' / '$$' / '$$$' for templates."""
        return "$" * int(self.budget_tier)

    @property
    def image_file(self) -> str:
        """
        Filename used for the card image, served from
        ``static/images/dest/``. Falls back to ``<slug>.png`` so a freshly
        dropped-in export named after the city slug is picked up with no
        data change. Presentation-only; never consulted by the engine.
        """
        return self.image or f"{self.slug}.png"

    @property
    def safety_label(self) -> str:
        """
        Short safety word for card meta lines ('Safe' / 'Moderate' /
        'Caution'), read from the most recent advisory. Empty when no
        advisory exists. Presentation-only convenience for templates.
        """
        advisory = self.safety_advisories.order_by("-captured_at").first()
        if advisory is None:
            return ""
        return advisory.get_level_display()


class Activity(models.Model):
    """A named attraction or experience within a city."""

    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name="activities")
    name = models.CharField(max_length=160)
    category = models.CharField(max_length=20, choices=ActivityCategory.choices)
    approx_price_eur = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text="Approximate entry / participation price in EUR.",
    )
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "activities"
        indexes = [models.Index(fields=["city", "category"], name="idx_activity_city_cat")]

    def __str__(self) -> str:
        return f"{self.name} ({self.city.name})"


# --- Freshness-aware abstract base -------------------------------------------


class TimestampedFact(models.Model):
    """
    Abstract base for any volatile, provenance-stamped observation.

    Concrete subclasses (weather, cost, safety) inherit `source` and
    `captured_at`, and a single `STALE_AFTER` policy that the intelligence
    layer consults via `is_stale`.
    """

    #: A fact older than this is considered stale. Overridable per subclass.
    STALE_AFTER: _dt.timedelta = _dt.timedelta(days=90)

    source = models.CharField(max_length=20, choices=DataSource.choices, default=DataSource.MANUAL)
    captured_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text="When this observation was captured from its source.",
    )

    class Meta:
        abstract = True

    @property
    def age(self) -> _dt.timedelta:
        """How long ago this fact was captured."""
        return timezone.now() - self.captured_at

    @property
    def is_stale(self) -> bool:
        """True when the fact is older than the subclass freshness policy."""
        return self.age > self.STALE_AFTER


# --- Volatile, time-grained facts --------------------------------------------


class MonthlyWeather(TimestampedFact):
    """
    Per-city, per-month climate norms. One row per (city, month). Weather
    norms shift slowly, so the staleness window is generous.
    """

    STALE_AFTER = _dt.timedelta(days=365)

    class Climate(models.TextChoices):
        WARM_SUNNY = "warm_sunny", "Warm & sunny"
        HOT_HUMID = "hot_humid", "Hot & humid"
        MILD = "mild", "Mild"
        COOL_DRY = "cool_dry", "Cool & dry"
        COLD = "cold", "Cold"

    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name="weather")
    month = models.PositiveSmallIntegerField(help_text="1 = January ... 12 = December")
    avg_high_c = models.SmallIntegerField(help_text="Average daily high (°C).")
    avg_low_c = models.SmallIntegerField(help_text="Average daily low (°C).")
    rainfall_mm = models.PositiveSmallIntegerField(default=0)
    climate_type = models.CharField(max_length=20, choices=Climate.choices, default=Climate.MILD)
    is_recommended_month = models.BooleanField(
        default=False, help_text="Flagged as one of the better months to visit."
    )

    class Meta:
        ordering = ["city", "month"]
        constraints = [
            models.UniqueConstraint(fields=["city", "month"], name="uniq_weather_city_month"),
            models.CheckConstraint(
                condition=models.Q(month__gte=1) & models.Q(month__lte=12),
                name="weather_month_in_range",
            ),
        ]
        indexes = [models.Index(fields=["city", "month"], name="idx_weather_city_month")]

    def __str__(self) -> str:
        return f"{self.city.name} — month {self.month}"


class CostSnapshot(TimestampedFact):
    """
    A point-in-time cost-of-travel snapshot for a city, broken down so the
    'Cost' tab and the budget factor in scoring can both be explained.
    """

    STALE_AFTER = _dt.timedelta(days=90)

    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name="cost_snapshots")
    daily_budget_eur = models.PositiveIntegerField(help_text="Daily cost for a budget traveller (EUR).")
    daily_midrange_eur = models.PositiveIntegerField(help_text="Daily cost for a mid-range traveller (EUR).")
    daily_luxury_eur = models.PositiveIntegerField(help_text="Daily cost for a luxury traveller (EUR).")
    hostel_night_eur = models.PositiveIntegerField(default=0)
    meal_cheap_eur = models.PositiveIntegerField(default=0)
    local_transport_day_eur = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-captured_at"]
        get_latest_by = "captured_at"
        indexes = [models.Index(fields=["city", "-captured_at"], name="idx_cost_city_recent")]

    def __str__(self) -> str:
        return f"{self.city.name} cost @ {self.captured_at:%Y-%m-%d}"


class SafetyAdvisory(TimestampedFact):
    """
    A point-in-time safety assessment. Government advisories change, so the
    staleness window is short and the latest row wins.
    """

    STALE_AFTER = _dt.timedelta(days=60)

    class Level(models.IntegerChoices):
        EXERCISE_CAUTION = 1, "Exercise Caution"
        MODERATE = 2, "Moderate"
        SAFE = 3, "Safe"

    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name="safety_advisories")
    safety_score = models.PositiveSmallIntegerField(help_text="0-100; higher is safer.")
    level = models.PositiveSmallIntegerField(choices=Level.choices, default=Level.MODERATE)
    health_notes = models.CharField(max_length=255, blank=True)
    advisory_summary = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-captured_at"]
        get_latest_by = "captured_at"
        verbose_name_plural = "safety advisories"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(safety_score__gte=0) & models.Q(safety_score__lte=100),
                name="safety_score_in_range",
            )
        ]
        indexes = [models.Index(fields=["city", "-captured_at"], name="idx_safety_city_recent")]

    def __str__(self) -> str:
        return f"{self.city.name} safety {self.safety_score}/100"
