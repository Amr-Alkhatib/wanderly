"""AI day-by-day itinerary for a city, generated with Gemini.

Design notes
------------
* One fast call by default. The itinerary asks Gemini for structured JSON
  (validated against a schema), so there is no fragile text parsing on the
  happy path.
* Hard time budget. Each call is capped at ``PER_CALL_TIMEOUT_S`` with the
  SDK's own retries switched off, and the whole fallback chain stops after
  ``TOTAL_BUDGET_S``, so a slow or broken model can never hang a request
  (and block the only web worker on small hosts).
* Cached. The same city + number of days is served from the cache for
  ``CACHE_SECONDS`` instead of calling the model again.
* Google Search grounding is opt-in (``GEMINI_GROUNDING=1``). It makes each
  call several seconds slower and has its own quota, and a sightseeing plan
  rarely needs live search results.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass

from django.core.cache import cache
from pydantic import BaseModel

logger = logging.getLogger(__name__)


@dataclass
class ItineraryDay:
    title: str
    morning: str
    afternoon: str
    evening: str
    morning_cost: int = 0
    afternoon_cost: int = 0
    evening_cost: int = 0


# --- Configuration -----------------------------------------------------------

#: Tried in order. The env var overrides the primary model without a code
#: change when Google retires a model. Check https://ai.google.dev/models.
GEMINI_MODELS: tuple[str, ...] = tuple(
    dict.fromkeys(
        m
        for m in (
            os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            "gemini-3.8-flash",
        )
        if m
    )
)

USE_GROUNDING = os.environ.get("GEMINI_GROUNDING", "0") == "1"
PER_CALL_TIMEOUT_S = int(os.environ.get("GEMINI_TIMEOUT_S", "15"))
TOTAL_BUDGET_S = int(os.environ.get("GEMINI_TOTAL_BUDGET_S", "30"))
CACHE_SECONDS = 60 * 60 * 24


# --- Prompt and response schema ----------------------------------------------

PROMPT = (
    "You are a travel planner. Create a {days}-day itinerary for {city}, {country}. "
    "Keep the daily budget around €{budget}. "
    "Give each day a short theme and exactly one activity for the morning, "
    "the afternoon and the evening, each with an estimated cost in whole euros "
    "(0 if free)."
)

#: Only used with grounding, where Gemini cannot also return strict JSON.
TEXT_FORMAT = (
    "\nReturn ONLY this exact format, one item per line, nothing else:\n"
    "DAY 1 | short theme for the day\n"
    "Morning | one activity | estimated euro cost\n"
    "Afternoon | one activity | estimated euro cost\n"
    "Evening | one activity | estimated euro cost\n"
    "Then repeat DAY 2, DAY 3, etc."
)


class _Slot(BaseModel):
    activity: str
    cost_eur: int


class _Day(BaseModel):
    theme: str
    morning: _Slot
    afternoon: _Slot
    evening: _Slot


class _Plan(BaseModel):
    days: list[_Day]


# --- Public entry point ------------------------------------------------------


def build_itinerary(city, days: int = 3) -> list[ItineraryDay]:
    """Return the itinerary, or an empty list if it could not be generated."""
    key = f"itinerary:v2:{city.pk}:{days}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    cost = city.cost_snapshots.order_by("-captured_at").first()
    budget = cost.daily_budget_eur if cost else 60
    prompt = PROMPT.format(
        days=days, city=city.name, country=city.country.name, budget=budget
    )

    try:
        plan = _generate(prompt)
    except Exception:
        logger.exception("Itinerary generation failed for %s", city.name)
        return []

    if plan:
        cache.set(key, plan, CACHE_SECONDS)
    return plan


# --- Gemini call ---------------------------------------------------------------


def _generate(prompt: str) -> list[ItineraryDay]:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set in the environment.")

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=PER_CALL_TIMEOUT_S * 1000,  # milliseconds
            retry_options=types.HttpRetryOptions(attempts=1),  # we handle fallback
        ),
    )

    deadline = time.monotonic() + TOTAL_BUDGET_S
    last_exc: Exception | None = None

    for model in GEMINI_MODELS:
        if time.monotonic() >= deadline:
            logger.warning("Itinerary time budget used up before trying %s", model)
            break
        started = time.monotonic()
        try:
            if USE_GROUNDING:
                config = types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                )
                resp = client.models.generate_content(
                    model=model, contents=prompt + TEXT_FORMAT, config=config
                )
                days = _parse(resp.text or "")
            else:
                config = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_Plan,
                )
                resp = client.models.generate_content(
                    model=model, contents=prompt, config=config
                )
                days = _from_plan(resp.parsed) or _from_json(resp.text or "")

            logger.info("Itinerary from %s in %.1fs", model, time.monotonic() - started)
            if days:
                return days
            logger.warning("%s returned an itinerary that could not be read", model)
        except Exception as exc:  # network errors, 404 model, 429 quota, timeout
            logger.warning(
                "Itinerary call to %s failed after %.1fs: %r",
                model, time.monotonic() - started, exc,
            )
            last_exc = exc

    if last_exc:
        raise last_exc
    return []


# --- Turning the response into ItineraryDay objects ---------------------------


def _from_plan(plan: object) -> list[ItineraryDay]:
    if not isinstance(plan, _Plan):
        return []
    return [
        ItineraryDay(
            title=d.theme,
            morning=d.morning.activity,
            afternoon=d.afternoon.activity,
            evening=d.evening.activity,
            morning_cost=max(0, d.morning.cost_eur),
            afternoon_cost=max(0, d.afternoon.cost_eur),
            evening_cost=max(0, d.evening.cost_eur),
        )
        for d in plan.days
    ]


def _from_json(text: str) -> list[ItineraryDay]:
    try:
        return _from_plan(_Plan.model_validate_json(text))
    except Exception:
        return []


_MARKDOWN = re.compile(r"[*_#`>]")
_LIST_PREFIX = re.compile(r"^(?:[-•]|\d+[.)])\s*")


def _parse(text: str) -> list[ItineraryDay]:
    """Parse the pipe-separated text format (used with grounding).

    Tolerates the markdown that grounded answers often add, such as
    ``**DAY 1** | ...`` or ``- Morning | ...``.
    """
    days: list[ItineraryDay] = []
    current: ItineraryDay | None = None
    for raw in text.splitlines():
        line = _LIST_PREFIX.sub("", _MARKDOWN.sub("", raw).strip())
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        label = parts[0].lower().rstrip(":")
        activity = parts[1] if len(parts) > 1 else ""
        cost = _to_cost(parts[2]) if len(parts) > 2 else 0
        if label.startswith("day"):
            if current:
                days.append(current)
            current = ItineraryDay(activity, "", "", "")
        elif current and label == "morning":
            current.morning, current.morning_cost = activity, cost
        elif current and label == "afternoon":
            current.afternoon, current.afternoon_cost = activity, cost
        elif current and label == "evening":
            current.evening, current.evening_cost = activity, cost
    if current:
        days.append(current)
    return days


def _to_cost(text: str) -> int:
    """'€15', '15 EUR', '10-20' and '1,200' all become a whole number."""
    match = re.search(r"\d+", text.replace(",", "").replace(".", ""))
    return int(match.group()) if match else 0
