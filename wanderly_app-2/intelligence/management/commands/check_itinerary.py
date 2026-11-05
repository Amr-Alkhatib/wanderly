"""Diagnose the AI itinerary step by step, without the web page in the way.

    python manage.py check_itinerary            # first city in the database
    python manage.py check_itinerary Lisbon     # a specific city

Prints the SDK version, whether the API key is set (never the key itself),
then calls each model once and shows the time taken and the exact error.
"""

from __future__ import annotations

import os
import time

from django.core.management.base import BaseCommand

from destinations.models import City
from intelligence import itinerary


class Command(BaseCommand):
    help = "Call Gemini once per configured model and report timing and errors."

    def add_arguments(self, parser):
        parser.add_argument("city", nargs="?", default=None)
        parser.add_argument("--days", type=int, default=3)

    def handle(self, *args, city=None, days=3, **options):
        try:
            import google.genai as genai_pkg
            from google import genai
            from google.genai import types
        except ImportError as exc:
            self.stderr.write(f"google-genai is not installed: {exc}")
            return

        key = os.environ.get("GEMINI_API_KEY", "")
        self.stdout.write(f"google-genai version : {getattr(genai_pkg, '__version__', 'unknown')}")
        self.stdout.write(f"GEMINI_API_KEY set   : {'yes (' + str(len(key)) + ' chars)' if key else 'NO'}")
        self.stdout.write(f"Models (in order)    : {', '.join(itinerary.GEMINI_MODELS)}")
        self.stdout.write(f"Grounding            : {'on' if itinerary.USE_GROUNDING else 'off'}")
        self.stdout.write(f"Timeouts             : {itinerary.PER_CALL_TIMEOUT_S}s per call, "
                          f"{itinerary.TOTAL_BUDGET_S}s total")
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        self.stdout.write(f"HTTPS proxy          : {proxy or 'none'}")
        if not key:
            self.stderr.write("Stop: set GEMINI_API_KEY in wanderly_app-2/.env first.")
            return

        qs = City.objects.select_related("country")
        target = qs.filter(name__iexact=city).first() if city else qs.first()
        if target is None:
            self.stderr.write("No city found. Seed the database first (seed_real or seed_demo).")
            return
        prompt = itinerary.PROMPT.format(
            days=days, city=target.name, country=target.country.name, budget=60
        )
        self.stdout.write(f"City                 : {target.name}, {target.country.name}\n")

        client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=30_000))
        config = types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=itinerary._Plan
        )
        for model in itinerary.GEMINI_MODELS:
            started = time.monotonic()
            try:
                resp = client.models.generate_content(model=model, contents=prompt, config=config)
                took = time.monotonic() - started
                parsed = itinerary._from_plan(resp.parsed) or itinerary._from_json(resp.text or "")
                if parsed:
                    self.stdout.write(self.style.SUCCESS(
                        f"OK   {model}: {took:.1f}s, {len(parsed)} days, "
                        f"day 1 = {parsed[0].title!r}"))
                else:
                    self.stdout.write(self.style.WARNING(
                        f"BAD  {model}: {took:.1f}s, answer could not be read: "
                        f"{(resp.text or '')[:300]!r}"))
            except Exception as exc:
                took = time.monotonic() - started
                self.stdout.write(self.style.ERROR(f"FAIL {model}: {took:.1f}s, {exc!r}"[:600]))

        self.stdout.write("\nNow through the real code path (with cache bypassed):")
        started = time.monotonic()
        try:
            result = itinerary._generate(prompt)
            self.stdout.write(f"_generate returned {len(result)} days in {time.monotonic() - started:.1f}s")
        except Exception as exc:
            self.stdout.write(self.style.ERROR(
                f"_generate raised after {time.monotonic() - started:.1f}s: {exc!r}"[:600]))
