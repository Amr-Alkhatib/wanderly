"""
`python manage.py seed_demo`

Populates the database with a small, realistic demo dataset so a fresh
checkout has something to rank and explain immediately. Idempotent:
re-running updates existing rows rather than duplicating them.

The data here is illustrative demo content (DataSource.SEED). In the real
pipeline these rows are written by the scraping / ABSA / weather-refresh
management commands instead.
"""

from __future__ import annotations

import datetime as _dt

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from destinations.models import (
    ActivityCategory,
    BudgetTier,
    City,
    CostSnapshot,
    Country,
    DataSource,
    MonthlyWeather,
    Region,
    SafetyAdvisory,
)
from intelligence.models import CityAspectScore


# (country, region, language, currency, [cities])
# Each city: name, emoji, image, card_pill, category, budget_tier, summary,
#            featured, cost(daily_budget/mid/lux), safety(score, level),
#            aspects {category: score}, recommended_months
_DATA = [
    (
        "Japan", Region.ASIA, "Japanese", "Japanese Yen (¥)",
        [
            ("Tokyo", "🗾", "japan.png", "Trending", ActivityCategory.CULTURAL, BudgetTier.MID_RANGE,
             "A blend of ancient tradition and cutting-edge modernity.", True,
             (50, 100, 220), (92, SafetyAdvisory.Level.SAFE),
             {ActivityCategory.FOOD: 96, ActivityCategory.CULTURAL: 94, ActivityCategory.CITY: 90},
             [3, 4, 10, 11]),
        ],
    ),
    (
        "Portugal", Region.EUROPE, "Portuguese", "Euro (€)",
        [
            ("Lisbon", "🇵🇹", "portugal.png", "Budget Pick", ActivityCategory.CITY, BudgetTier.BUDGET,
             "Sun-soaked hills, tile-clad streets and easy coastal escapes.", True,
             (35, 70, 150), (88, SafetyAdvisory.Level.SAFE),
             {ActivityCategory.CITY: 92, ActivityCategory.FOOD: 88, ActivityCategory.BEACH: 80},
             [4, 5, 6, 9, 10]),
        ],
    ),
    (
        "Morocco", Region.AFRICA, "Arabic / Berber", "Moroccan Dirham (MAD)",
        [
            ("Marrakech", "🕌", "morocco.png", "Cultural", ActivityCategory.CULTURAL, BudgetTier.BUDGET,
             "Souks, palaces and desert gateways steeped in colour.", True,
             (30, 65, 140), (66, SafetyAdvisory.Level.MODERATE),
             {ActivityCategory.CULTURAL: 90, ActivityCategory.FOOD: 82, ActivityCategory.ADVENTURE: 78},
             [3, 4, 5, 10, 11]),
        ],
    ),
    (
        "Vietnam", Region.ASIA, "Vietnamese", "Vietnamese Dong (₫)",
        [
            ("Hanoi", "🍜", "vietnam.png", "Food Scene", ActivityCategory.FOOD, BudgetTier.BUDGET,
             "Street-food capital with lakes, old quarters and rich history.", True,
             (25, 55, 120), (84, SafetyAdvisory.Level.SAFE),
             {ActivityCategory.FOOD: 95, ActivityCategory.CULTURAL: 82, ActivityCategory.CITY: 78},
             [10, 11, 12, 3, 4]),
        ],
    ),
    (
        "India", Region.ASIA, "Malayalam / English", "Indian Rupee (₹)",
        [
            ("Kerala", "🌿", "", "", ActivityCategory.NATURE, BudgetTier.BUDGET,
             "Backwaters, tea hills and palm-fringed coast — 'God's own country'.", False,
             (20, 45, 100), (78, SafetyAdvisory.Level.MODERATE),
             {ActivityCategory.NATURE: 93, ActivityCategory.BEACH: 84, ActivityCategory.FOOD: 80},
             [11, 12, 1, 2]),
        ],
    ),
    (
        "Albania", Region.EUROPE, "Albanian", "Albanian Lek (L)",
        [
            ("Tirana", "🏖️", "albania.png", "", ActivityCategory.BEACH, BudgetTier.BUDGET,
             "Europe's affordable Riviera with beaches and rugged mountains.", False,
             (20, 60, 110), (80, SafetyAdvisory.Level.MODERATE),
             {ActivityCategory.BEACH: 88, ActivityCategory.NATURE: 82, ActivityCategory.CITY: 70},
             [5, 6, 7, 9]),
        ],
    ),
    (
        "Georgia", Region.ASIA, "Georgian", "Georgian Lari (₾)",
        [
            ("Tbilisi", "⛰️", "georgia.png", "", ActivityCategory.CULTURAL, BudgetTier.BUDGET,
             "Wine country, sulphur baths and old-town charm where Europe meets Asia.", False,
             (18, 45, 95), (85, SafetyAdvisory.Level.SAFE),
             {ActivityCategory.CULTURAL: 86, ActivityCategory.FOOD: 88, ActivityCategory.NATURE: 84},
             [5, 6, 9, 10]),
        ],
    ),
    (
        "Sri Lanka", Region.ASIA, "Sinhala / Tamil", "Sri Lankan Rupee (Rs)",
        [
            ("Colombo", "🌴", "srilanka.png", "", ActivityCategory.NATURE, BudgetTier.BUDGET,
             "Tea highlands, ancient temples and palm-lined southern beaches.", False,
             (22, 50, 110), (74, SafetyAdvisory.Level.MODERATE),
             {ActivityCategory.NATURE: 90, ActivityCategory.BEACH: 86, ActivityCategory.CULTURAL: 80},
             [1, 2, 3, 12]),
        ],
    ),
    (
        "North Macedonia", Region.EUROPE, "Macedonian", "Macedonian Denar (ден)",
        [
            ("Skopje", "🏛️", "nmacedonia.png", "", ActivityCategory.CITY, BudgetTier.BUDGET,
             "Lakeside towns, Ottoman bazaars and some of the Balkans' best value.", False,
             (15, 40, 85), (82, SafetyAdvisory.Level.SAFE),
             {ActivityCategory.CITY: 78, ActivityCategory.CULTURAL: 80, ActivityCategory.NATURE: 82},
             [5, 6, 9, 10]),
        ],
    ),
    (
        "Kosovo", Region.EUROPE, "Albanian / Serbian", "Euro (€)",
        [
            ("Pristina", "🗻", "kosovo.png", "", ActivityCategory.CITY, BudgetTier.BUDGET,
             "Europe's youngest country: cheap, friendly and refreshingly off-radar.", False,
             (12, 35, 75), (81, SafetyAdvisory.Level.SAFE),
             {ActivityCategory.CITY: 74, ActivityCategory.CULTURAL: 76, ActivityCategory.ADVENTURE: 78},
             [5, 6, 7, 9]),
        ],
    ),
]


class Command(BaseCommand):
    help = "Populate the database with a small, idempotent demo dataset."

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> None:
        now = timezone.now()
        cities_created = 0

        for c_name, region, language, currency, cities in _DATA:
            country, _ = Country.objects.update_or_create(
                name=c_name,
                defaults={
                    "region": region,
                    "language": language,
                    "currency": currency,
                    "visa_summary": "EU/US citizens: typically visa-free for short stays.",
                },
            )

            for (
                name, emoji, image, card_pill, category, budget_tier, summary,
                featured, cost, safety, aspects, rec_months,
            ) in cities:
                city, created = City.objects.update_or_create(
                    country=country,
                    name=name,
                    defaults={
                        "summary": summary,
                        "primary_category": category,
                        "budget_tier": budget_tier,
                        "emoji": emoji,
                        "image": image,
                        "card_pill": card_pill,
                        "is_featured": featured,
                    },
                )
                cities_created += int(created)

                budget_d, mid_d, lux_d = cost
                CostSnapshot.objects.update_or_create(
                    city=city,
                    captured_at=now,
                    defaults={
                        "daily_budget_eur": budget_d,
                        "daily_midrange_eur": mid_d,
                        "daily_luxury_eur": lux_d,
                        "hostel_night_eur": max(10, budget_d // 2),
                        "meal_cheap_eur": max(3, budget_d // 8),
                        "local_transport_day_eur": max(2, budget_d // 10),
                        "source": DataSource.SEED,
                    },
                )

                score, level = safety
                SafetyAdvisory.objects.update_or_create(
                    city=city,
                    captured_at=now,
                    defaults={
                        "safety_score": score,
                        "level": level,
                        "health_notes": "Standard precautions advised.",
                        "advisory_summary": "No major travel restrictions.",
                        "source": DataSource.SEED,
                    },
                )

                for aspect, value in aspects.items():
                    CityAspectScore.objects.update_or_create(
                        city=city,
                        aspect=aspect,
                        defaults={"score": value, "sample_size": 120},
                    )

                # Twelve months of simple synthetic climate norms.
                for month in range(1, 13):
                    high = 18 + 10 * (1 if month in {5, 6, 7, 8} else 0)
                    MonthlyWeather.objects.update_or_create(
                        city=city,
                        month=month,
                        defaults={
                            "avg_high_c": high,
                            "avg_low_c": high - 8,
                            "rainfall_mm": 60 if month in {6, 7, 8} else 30,
                            "climate_type": (
                                MonthlyWeather.Climate.WARM_SUNNY
                                if month in rec_months
                                else MonthlyWeather.Climate.MILD
                            ),
                            "is_recommended_month": month in rec_months,
                            "source": DataSource.SEED,
                        },
                    )

        total = City.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Seed complete: {cities_created} new cities ({total} total), "
                "with cost, safety, weather and aspect data."
            )
        )
