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


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class HomePageTests(TestCase):
    def setUp(self):
        pt = Country.objects.create(name="Portugal", region=Region.EUROPE)
        city = City.objects.create(
            country=pt, name="Lisbon", primary_category=ActivityCategory.CITY,
            budget_tier=BudgetTier.BUDGET,
        )
        CostSnapshot.objects.create(city=city, daily_budget_eur=40, daily_midrange_eur=80,
                                    daily_luxury_eur=160, captured_at=timezone.now())

    def test_daily_cost_is_shown_in_euros(self):
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, "€40/day")
        self.assertNotContains(resp, "$40/day")

    def test_category_tiles_match_the_category_they_filter_by(self):
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, '?category=cultural">Culture</a>', html=False)
        self.assertNotContains(resp, ">History</a>")


class DeploymentSettingsTests(TestCase):
    """Settings must refuse the public fallback key once DEBUG is off."""

    def _load_settings(self, **env):
        import os
        import subprocess
        import sys
        from pathlib import Path

        clean = {k: v for k, v in os.environ.items() if not k.startswith("DJANGO_")}
        clean.update(env)
        return subprocess.run(
            [sys.executable, "-c", "import wanderly.settings"],
            cwd=Path(__file__).resolve().parent.parent, env=clean,
            capture_output=True, text=True,
        )

    def test_debug_off_without_secret_key_fails_loudly(self):
        result = self._load_settings(DJANGO_DEBUG="0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY is not set", result.stderr)

    def test_debug_off_with_secret_key_loads(self):
        result = self._load_settings(DJANGO_DEBUG="0", DJANGO_SECRET_KEY="x" * 50)
        self.assertEqual(result.returncode, 0, result.stderr)
