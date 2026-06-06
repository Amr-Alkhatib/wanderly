"""
Tests for the deterministic recommendation engine and the Explainer seam.

Three commitments are verified here, matching the project's core promises:

1. Ranking correctness   -- a cheaper/safer city outranks a worse one, and
                            the ordering is stable.
2. Explainability        -- every score carries a factor breakdown whose
                            weighted points reconstruct the total, and
                            `.explain()` names the factors.
3. Stale-data flagging   -- a city scored from aging data is marked so the
                            UI can be honest about confidence.

A fourth test pins the architectural invariant that the Explainer never
changes the score it is given.
"""

from __future__ import annotations

import datetime as _dt

from django.test import TestCase
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
from intelligence.engine import Preferences, RecommendationEngine, ScoredCity
from intelligence.explainers import NullExplainer
from intelligence.models import CityAspectScore


def _make_city(name: str, *, budget: int, safety: int, fresh: bool = True) -> City:
    """Create a city with one cost + one safety row, fresh or stale."""
    country, _ = Country.objects.get_or_create(
        name=f"Country-{name}", defaults={"region": Region.ASIA}
    )
    city = City.objects.create(
        country=country,
        name=name,
        primary_category=ActivityCategory.CITY,
        budget_tier=BudgetTier.BUDGET,
    )
    captured = timezone.now()
    if not fresh:
        # Older than CostSnapshot.STALE_AFTER (90d) and SafetyAdvisory (60d).
        captured = timezone.now() - _dt.timedelta(days=400)

    CostSnapshot.objects.create(
        city=city,
        captured_at=captured,
        daily_budget_eur=budget,
        daily_midrange_eur=budget * 2,
        daily_luxury_eur=budget * 4,
        source=DataSource.SEED,
    )
    SafetyAdvisory.objects.create(
        city=city,
        captured_at=captured,
        safety_score=safety,
        level=SafetyAdvisory.Level.SAFE,
        source=DataSource.SEED,
    )
    return city


class RankingCorrectnessTests(TestCase):
    def test_cheaper_and_safer_city_ranks_higher(self) -> None:
        cheap_safe = _make_city("CheapSafe", budget=30, safety=95)
        pricey_risky = _make_city("PriceyRisky", budget=300, safety=40)

        engine = RecommendationEngine(Preferences(max_daily_budget_eur=80, safety_priority=5))
        ranked = engine.rank([pricey_risky, cheap_safe])

        self.assertEqual(ranked[0].city, cheap_safe)
        self.assertGreater(ranked[0].score, ranked[1].score)

    def test_ranking_is_stable_for_ties(self) -> None:
        a = _make_city("Alpha", budget=50, safety=80)
        b = _make_city("Bravo", budget=50, safety=80)
        engine = RecommendationEngine()
        ranked = engine.rank([b, a])
        # Equal scores -> alphabetical by name, deterministically.
        self.assertEqual([sc.city.name for sc in ranked], ["Alpha", "Bravo"])

    def test_score_is_clamped_to_0_100(self) -> None:
        city = _make_city("Edge", budget=10, safety=100)
        engine = RecommendationEngine(Preferences(max_daily_budget_eur=500, safety_priority=5))
        scored = engine.score_city(city)
        self.assertGreaterEqual(scored.score, 0)
        self.assertLessEqual(scored.score, 100)


class ExplainabilityTests(TestCase):
    def test_breakdown_reconstructs_total(self) -> None:
        city = _make_city("Explainville", budget=40, safety=85)
        scored = RecommendationEngine().score_city(city)

        summed = round(sum(f.points for f in scored.factors))
        summed = max(0, min(100, summed))
        self.assertEqual(scored.score, summed)

    def test_explain_names_every_factor(self) -> None:
        city = _make_city("Whyton", budget=40, safety=85)
        scored = RecommendationEngine().score_city(city)
        text = scored.explain()
        for factor in scored.factors:
            self.assertIn(factor.name, text)

    def test_interest_factor_uses_aspect_scores(self) -> None:
        city = _make_city("Foodtown", budget=40, safety=80)
        CityAspectScore.objects.create(city=city, aspect=ActivityCategory.FOOD, score=98)

        no_pref = RecommendationEngine().score_city(city)
        foodie = RecommendationEngine(
            Preferences(interests=(ActivityCategory.FOOD,))
        ).score_city(city)

        no_pref_interest = next(f for f in no_pref.factors if f.name == "Interests")
        foodie_interest = next(f for f in foodie.factors if f.name == "Interests")
        self.assertGreater(foodie_interest.raw_score, no_pref_interest.raw_score)
        self.assertIn("food", foodie_interest.detail.lower())


class StaleDataTests(TestCase):
    def test_stale_inputs_are_flagged(self) -> None:
        fresh = _make_city("FreshCity", budget=40, safety=85, fresh=True)
        stale = _make_city("StaleCity", budget=40, safety=85, fresh=False)

        engine = RecommendationEngine()
        self.assertFalse(engine.score_city(fresh).has_stale_inputs)

        stale_scored = engine.score_city(stale)
        self.assertTrue(stale_scored.has_stale_inputs)
        self.assertIn("stale", stale_scored.explain().lower())

    def test_missing_data_is_treated_as_stale(self) -> None:
        country, _ = Country.objects.get_or_create(
            name="Country-Empty", defaults={"region": Region.ASIA}
        )
        bare = City.objects.create(country=country, name="Bare")
        scored = RecommendationEngine().score_city(bare)
        # No cost/safety rows -> those factors are flagged stale.
        self.assertTrue(scored.has_stale_inputs)


class ExplainerInvariantTests(TestCase):
    def test_null_explainer_never_changes_score(self) -> None:
        city = _make_city("Stable", budget=40, safety=85)
        scored = RecommendationEngine().score_city(city)
        before = scored.score
        prose = NullExplainer().explain(scored)

        self.assertEqual(scored.score, before)  # explaining is read-only
        self.assertIn(str(before), prose)  # the prose cites the real score
