"""Tests for the deterministic comparison builder."""
from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from destinations.models import (
    ActivityCategory, BudgetTier, City, CostSnapshot, Country,
    Region, SafetyAdvisory,
)
from intelligence.engine import Preferences, RecommendationEngine
from intelligence.comparison import build_comparison


class ComparisonBuilderTests(TestCase):
    def setUp(self) -> None:
        now = timezone.now()
        self.jp = Country.objects.create(name="Japan", region=Region.ASIA)
        self.pt = Country.objects.create(name="Portugal", region=Region.EUROPE)
        self.tokyo = City.objects.create(
            country=self.jp, name="Tokyo", primary_category=ActivityCategory.CULTURAL,
            budget_tier=BudgetTier.MID_RANGE,
        )
        self.lisbon = City.objects.create(
            country=self.pt, name="Lisbon", primary_category=ActivityCategory.CITY,
            budget_tier=BudgetTier.BUDGET,
        )
        CostSnapshot.objects.create(city=self.tokyo, daily_budget_eur=50,
                                    daily_midrange_eur=100, daily_luxury_eur=220, captured_at=now)
        CostSnapshot.objects.create(city=self.lisbon, daily_budget_eur=35,
                                    daily_midrange_eur=70, daily_luxury_eur=150, captured_at=now)
        SafetyAdvisory.objects.create(city=self.tokyo, safety_score=92,
                                      level=SafetyAdvisory.Level.SAFE, captured_at=now)
        SafetyAdvisory.objects.create(city=self.lisbon, safety_score=88,
                                      level=SafetyAdvisory.Level.SAFE, captured_at=now)

    def _scored(self):
        eng = RecommendationEngine(Preferences.for_anonymous())
        return [eng.score_city(self.tokyo), eng.score_city(self.lisbon)]

    def test_cheaper_city_wins_budget_row(self) -> None:
        result = build_comparison(self._scored())
        budget = next(r for r in result.rows if r.label == "Daily Budget")
        # Lisbon (index 1) is cheaper -> it should be the winner.
        self.assertFalse(budget.cells[0].is_winner)
        self.assertTrue(budget.cells[1].is_winner)

    def test_safer_city_wins_safety_row(self) -> None:
        result = build_comparison(self._scored())
        safety = next(r for r in result.rows if r.label == "Safety Score")
        self.assertTrue(safety.cells[0].is_winner)   # Tokyo 92
        self.assertFalse(safety.cells[1].is_winner)  # Lisbon 88

    def test_textual_row_has_no_winner(self) -> None:
        result = build_comparison(self._scored())
        visa = next(r for r in result.rows if r.label == "Visa (EU/DE)")
        self.assertFalse(any(c.is_winner for c in visa.cells))

    def test_verdicts_match_row_winners(self) -> None:
        result = build_comparison(self._scored())
        labels = dict(result.verdicts)
        self.assertEqual(labels["Best for Budget"], "Portugal")
        self.assertEqual(labels["Best for Safety"], "Japan")

    def test_every_row_is_fully_populated(self) -> None:
        result = build_comparison(self._scored())
        for r in result.rows:
            self.assertEqual(len(r.cells), 2)
            for c in r.cells:
                self.assertTrue(c.display)  # no empty cells in the UI
