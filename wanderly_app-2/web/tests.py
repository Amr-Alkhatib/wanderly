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


class _BodyAttrs(__import__("html.parser").parser.HTMLParser):
    """Collects the attributes of <body> (the parser undoes Django's HTML escaping, like a browser)."""
    attrs: dict = {}

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.attrs = dict(attrs)


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class SaveAndPlanTests(TestCase):
    """Save buttons and "Plan a trip" on the destination and country pages."""

    def setUp(self):
        from accounts.models import User
        now = timezone.now()
        self.country = Country.objects.create(name="Portugal", region=Region.EUROPE)
        self.city = City.objects.create(
            country=self.country, name="Lisbon", primary_category=ActivityCategory.CITY,
            budget_tier=BudgetTier.BUDGET, is_featured=True,
        )
        CostSnapshot.objects.create(city=self.city, daily_budget_eur=40,
                                    daily_midrange_eur=80, daily_luxury_eur=160, captured_at=now)
        SafetyAdvisory.objects.create(city=self.city, safety_score=86,
                                      level=SafetyAdvisory.Level.SAFE, captured_at=now)
        self.user = User.objects.create(email="t@example.com", supabase_uid="uid-1")
        self.page = reverse("destination", args=[self.city.slug])

    def test_saved_trips_reach_the_page_as_valid_json(self):
        # Printed into a <script>, an escaped map ({&quot;lisbon&quot;: ...}) was a syntax error that
        # broke every save button on the page as soon as one trip was saved.
        self.client.force_login(self.user)
        saved = {"lisbon": "trip-1", "tokyo": "trip-2"}
        with mock.patch("web.views_saved.get_saved_trip_map", return_value=saved):
            resp = self.client.get(self.page)
        parser = _BodyAttrs()
        parser.feed(resp.content.decode())
        import json
        self.assertEqual(json.loads(parser.attrs["data-saved-trips"]), saved)
        self.assertIn("data-signed-in", parser.attrs)
        self.assertNotContains(resp, "_SAVED_MAP")

    def test_destination_save_buttons_are_real_buttons(self):
        resp = self.client.get(self.page)
        import re
        buttons = re.findall(r'<button[^>]*\sdata-save[\s>][^>]*data-destination="lisbon"', resp.content.decode())
        self.assertEqual(len(buttons), 2)  # the hero button and the sidebar one
        self.assertNotContains(resp, 'href="#" class="cp-cta-btn')
        self.assertContains(resp, "js/wanderly/saves.js")

    def test_plan_a_trip_goes_to_this_citys_overview(self):
        resp = self.client.get(self.page)
        self.assertContains(resp, "Plan a trip to Lisbon")
        self.assertContains(resp, 'href="#tab-overview" class="cp-cta-btn" data-plan-trip')

    def test_country_plan_a_trip_goes_to_its_lead_citys_overview(self):
        resp = self.client.get(reverse("country_profile", args=[self.country.slug]))
        self.assertContains(resp, f'href="{self.page}#tab-overview"')
        self.assertContains(resp, "Plan a trip to Lisbon")
