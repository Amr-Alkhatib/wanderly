"""Tests for the Gemini itinerary: parsing, fallback, time budget and caching.

No network access: the Gemini client is replaced by a fake.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from intelligence import itinerary
from intelligence.itinerary import (
    ItineraryDay,
    _Day,
    _Plan,
    _Slot,
    _from_json,
    _parse,
    _to_cost,
    build_itinerary,
)


def _city(pk: int = 1):
    snapshots = SimpleNamespace(order_by=lambda *_: SimpleNamespace(first=lambda: None))
    return SimpleNamespace(
        pk=pk, name="Porto", country=SimpleNamespace(name="Portugal"),
        cost_snapshots=snapshots,
    )


def _plan(theme: str = "Old town") -> _Plan:
    slot = lambda a, c: _Slot(activity=a, cost_eur=c)  # noqa: E731
    return _Plan(days=[_Day(
        theme=theme,
        morning=slot("Walking tour", 0),
        afternoon=slot("Museum", 15),
        evening=slot("Dinner", 25),
    )])


class FakeModels:
    """Stands in for client.models; each model name maps to a result or an error."""

    def __init__(self, behaviour: dict[str, object]):
        self.behaviour = behaviour
        self.calls: list[str] = []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        outcome = self.behaviour[model]
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(parsed=outcome, text="")


class ParsingTests(SimpleTestCase):
    def test_parse_tolerates_markdown_from_grounded_answers(self):
        text = (
            "**DAY 1** | Old town\n"
            "- **Morning** | Walking tour | €0\n"
            "- **Afternoon** | Museum | €15\n"
            "- **Evening** | Dinner | 25 EUR\n"
        )
        self.assertEqual(
            _parse(text),
            [ItineraryDay("Old town", "Walking tour", "Museum", "Dinner", 0, 15, 25)],
        )

    def test_to_cost_reads_common_formats(self):
        self.assertEqual(_to_cost("€15"), 15)
        self.assertEqual(_to_cost("25 EUR"), 25)
        self.assertEqual(_to_cost("10-20"), 10)
        self.assertEqual(_to_cost("1,200"), 1200)
        self.assertEqual(_to_cost("free"), 0)

    def test_from_json_reads_structured_output(self):
        days = _from_json(_plan().model_dump_json())
        self.assertEqual(days[0].title, "Old town")
        self.assertEqual(days[0].afternoon_cost, 15)

    def test_from_json_rejects_garbage(self):
        self.assertEqual(_from_json("not json"), [])


@mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
class GenerateTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def _run(self, behaviour):
        fake = FakeModels(behaviour)
        client = SimpleNamespace(models=fake)
        with mock.patch("google.genai.Client", return_value=client), \
             mock.patch.object(itinerary, "GEMINI_MODELS", tuple(behaviour)):
            result = itinerary._generate("prompt")
        return result, fake.calls

    def test_falls_back_to_the_next_model_when_one_fails(self):
        days, calls = self._run({
            "missing-model": RuntimeError("404 model not found"),
            "good-model": _plan(),
        })
        self.assertEqual(calls, ["missing-model", "good-model"])
        self.assertEqual(days[0].evening, "Dinner")

    def test_stops_when_the_time_budget_is_used_up(self):
        with mock.patch.object(itinerary, "TOTAL_BUDGET_S", 0):
            days, calls = self._run({"a": _plan(), "b": _plan()})
        self.assertEqual(calls, [])
        self.assertEqual(days, [])

    def test_raises_last_error_when_every_model_fails(self):
        with self.assertRaises(RuntimeError):
            self._run({"a": RuntimeError("quota"), "b": RuntimeError("timeout")})


class BuildItineraryTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_result_is_cached_per_city_and_days(self):
        days = [ItineraryDay("Old town", "Tour", "Museum", "Dinner")]
        with mock.patch.object(itinerary, "_generate", return_value=days) as gen:
            self.assertEqual(build_itinerary(_city(), 3), days)
            self.assertEqual(build_itinerary(_city(), 3), days)
            build_itinerary(_city(), 4)
        self.assertEqual(gen.call_count, 2)  # second (city, 3) came from the cache

    def test_failure_returns_empty_list_and_is_not_cached(self):
        with mock.patch.object(itinerary, "_generate", side_effect=RuntimeError("down")) as gen:
            self.assertEqual(build_itinerary(_city(), 3), [])
            self.assertEqual(build_itinerary(_city(), 3), [])
        self.assertEqual(gen.call_count, 2)
