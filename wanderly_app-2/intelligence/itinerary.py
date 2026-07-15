from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ItineraryDay:
    title: str
    morning: str
    afternoon: str
    evening: str
    morning_cost: int = 0
    afternoon_cost: int = 0
    evening_cost: int = 0

PROMPT = (
    "You are a travel planner. Create a {days}-day itinerary for {city}, {country}. "
    "Keep the daily budget around €{budget}. "
    "For each activity, add an estimated cost in euros as a plain number (0 if free). "
    "Return ONLY this exact format, one item per line, nothing else:\n"
    "DAY 1 | short theme for the day\n"
    "Morning | one activity | estimated euro cost\n"
    "Afternoon | one activity | estimated euro cost\n"
    "Evening | one activity | estimated euro cost\n"
    "Then repeat DAY 2, DAY 3, etc."
)

def build_itinerary(city, days: int = 3) -> list[ItineraryDay]:
    cost = city.cost_snapshots.order_by("-captured_at").first()
    budget = cost.daily_budget_eur if cost else 60
    prompt = PROMPT.format(
        days=days, city=city.name, country=city.country.name, budget=budget
    )
    try:
        return _parse(_complete(prompt))
    except Exception as exc:
        print(f"[build_itinerary] ERROR: {exc}")
        return []

#: Overridable so future model deprecations don't require a code change.
#: Tried in order; env var can override the primary without a redeploy.
GEMINI_MODELS: tuple[str, ...] = (
    os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"),
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
)

#: If "1" (default), an ungrounded call is allowed as the very last resort
#: so users get an itinerary even when grounding capacity is exhausted.
ALLOW_UNGROUNDED_FALLBACK = os.environ.get("GEMINI_ALLOW_UNGROUNDED", "1") == "1"


def _complete(prompt: str) -> str:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set in the environment.")

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=25_000),  # 25s cap per attempt
    )
    grounded_config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
    )

    last_exc: Exception | None = None

    # Pass 1: every model WITH Google Search grounding.
    for model in GEMINI_MODELS:
        try:
            resp = client.models.generate_content(
                model=model, contents=prompt, config=grounded_config
            )
            if resp.text:
                return resp.text
        except Exception as exc:
            print(f"[_complete] grounded {model} failed: {exc!r}")
            last_exc = exc

    # Pass 2 (last resort): primary model without grounding.
    if ALLOW_UNGROUNDED_FALLBACK:
        for model in GEMINI_MODELS:
            try:
                print(f"[_complete] falling back to ungrounded {model}")
                resp = client.models.generate_content(model=model, contents=prompt)
                if resp.text:
                    return resp.text
            except Exception as exc:
                print(f"[_complete] ungrounded {model} failed: {exc!r}")
                last_exc = exc

    raise last_exc or RuntimeError("All Gemini attempts failed.")


def _parse(text: str) -> list[ItineraryDay]:
    days: list[ItineraryDay] = []
    current: ItineraryDay | None = None
    for line in text.splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        label = parts[0].lower()
        activity = parts[1] if len(parts) > 1 else ""
        cost = _to_cost(parts[2]) if len(parts) > 2 else 0
        if label.startswith("day"):
            if current:
                days.append(current)
            current = ItineraryDay(activity, "", "", "")
        elif current and label == "morning":
            current.morning = activity
            current.morning_cost = cost
        elif current and label == "afternoon":
            current.afternoon = activity
            current.afternoon_cost = cost
        elif current and label == "evening":
            current.evening = activity
            current.evening_cost = cost
    if current:
        days.append(current)
    return days

def _to_cost(text: str) -> int:
    text = text.replace("€", "").strip()
    try:
        return int(text)
    except ValueError:
        return 0