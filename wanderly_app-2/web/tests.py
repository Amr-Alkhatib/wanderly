"""Tests for the destination page and the itinerary endpoint.

The page must never wait for Gemini; the endpoint does the slow work.
"""

from __future__ import annotations

from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from destinations.models import (
    ActivityCategory, BudgetTier, City, CostSnapshot, Country, Region,
    SafetyAdvisory,
)
from intelligence.itinerary import ItineraryDay

PLAN = [ItineraryDay("Old town", "Walking tour", "Tile museum", "Fado dinner", 0, 8, 35)]


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class ItineraryFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        now = timezone.now()
        pt = Country.objects.create(name="Portugal", region=Region.EUROPE)
        self.city = City.objects.create(
            country=pt, name="Lisbon", primary_category=ActivityCategory.CITY,
            budget_tier=BudgetTier.BUDGET,
        )
        CostSnapshot.objects.create(city=self.city, daily_budget_eur=40,
                                    daily_midrange_eur=80, daily_luxury_eur=160, captured_at=now)
        SafetyAdvisory.objects.create(city=self.city, safety_score=86,
                                      level=SafetyAdvisory.Level.SAFE, captured_at=now)
        self.page = reverse("destination", args=[self.city.slug])
        self.fragment = reverse("itinerary_fragment", args=[self.city.slug])

    def test_page_does_not_call_gemini_and_marks_itinerary_pending(self):
        with mock.patch("intelligence.itinerary._generate") as gen:
            resp = self.client.get(self.page + "?itinerary=1&days=3")
        self.assertEqual(resp.status_code, 200)
        gen.assert_not_called()
        self.assertContains(resp, 'data-pending="3"')

    def test_page_shows_cached_itinerary_immediately(self):
        with mock.patch("intelligence.itinerary._generate", return_value=PLAN):
            self.client.get(self.fragment + "?days=3")  # fills the cache
        with mock.patch("intelligence.itinerary._generate") as gen:
            resp = self.client.get(self.page + "?itinerary=1&days=3")
        gen.assert_not_called()
        self.assertContains(resp, "Fado dinner")
        self.assertNotContains(resp, "data-pending")

    def test_fragment_returns_itinerary_html_and_timing(self):
        with mock.patch("intelligence.itinerary._generate", return_value=PLAN):
            resp = self.client.get(self.fragment + "?days=3")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Day 1 · Old town")
        self.assertContains(resp, "€43")  # 0 + 8 + 35 activity cost in the summary
        self.assertIn("X-Itinerary-Seconds", resp.headers)

    def test_fragment_failure_returns_503_with_retry_button(self):
        with mock.patch("intelligence.itinerary._generate", side_effect=RuntimeError("down")):
            resp = self.client.get(self.fragment + "?days=5")
        self.assertEqual(resp.status_code, 503)
        self.assertContains(resp, "itin-retry", status_code=503)
